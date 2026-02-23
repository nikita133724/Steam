"""
БАЗА ДАННЫХ
"""
import sqlite3
import json
import time
from config import DB_PATH, HOT_LAYER_DAYS, WARM_LAYER_DAYS


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            username    TEXT NOT NULL,
            content     TEXT NOT NULL,
            role        INTEGER DEFAULT 1,
            created_at  INTEGER NOT NULL,
            vector      BLOB,
            is_bot      INTEGER DEFAULT 0,
            is_me       INTEGER DEFAULT 0,
            layer       TEXT DEFAULT 'hot'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id         INTEGER PRIMARY KEY,
            username        TEXT NOT NULL,
            all_usernames   TEXT DEFAULT '[]',
            role            INTEGER DEFAULT 1,
            first_seen      INTEGER NOT NULL,
            last_seen       INTEGER NOT NULL,
            message_count   INTEGER DEFAULT 0,
            relationship    TEXT DEFAULT 'neutral',
            notes           TEXT DEFAULT '',
            portrait        TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       INTEGER NOT NULL,
            trigger_msg_id  INTEGER,
            decision        TEXT NOT NULL,
            reason          TEXT,
            sent_text       TEXT,
            tokens_used     INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   INTEGER NOT NULL,
            context     TEXT,
            wrong       TEXT,
            right       TEXT,
            user_id     INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] База данных инициализирована")


def save_message(msg_id, user_id, username, content, role, created_at,
                 vector=None, is_bot=False, is_me=False):
    conn = get_conn()
    try:
        vector_blob = vector.tobytes() if vector is not None else None
        conn.execute("""
            INSERT OR IGNORE INTO messages
            (id, user_id, username, content, role, created_at, vector, is_bot, is_me)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, user_id, username, content, role,
              created_at, vector_blob, int(is_bot), int(is_me)))
        conn.commit()
    finally:
        conn.close()


def get_last_messages(limit=15):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT username, content, is_bot, is_me, created_at, role
            FROM messages ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def get_last_message_id():
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM state WHERE key='last_msg_id'").fetchone()
        return int(row['value']) if row else 0
    finally:
        conn.close()


def set_last_message_id(msg_id):
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('last_msg_id', ?)",
                     (str(msg_id),))
        conn.commit()
    finally:
        conn.close()


def get_state(key, default=None):
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default
    finally:
        conn.close()


def set_state(key, value):
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                     (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def get_bot_sent_messages(limit=20):
    conn = get_conn()
    try:
        return conn.execute("""
            SELECT content, created_at FROM messages
            WHERE is_bot = 1 ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()


def upsert_user(user_id, username, role):
    now = int(time.time())
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            all_names = json.loads(row['all_usernames'])
            if username not in all_names:
                all_names.append(username)
            conn.execute("""
                UPDATE users SET username=?, all_usernames=?, role=?,
                last_seen=?, message_count=message_count+1 WHERE user_id=?
            """, (username, json.dumps(all_names, ensure_ascii=False), role, now, user_id))
        else:
            conn.execute("""
                INSERT INTO users
                (user_id, username, all_usernames, role, first_seen, last_seen, message_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (user_id, username, json.dumps([username], ensure_ascii=False), role, now, now))
        conn.commit()
    finally:
        conn.close()


def get_user_profile(user_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()


def update_user_notes(user_id, notes):
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET notes=? WHERE user_id=?", (notes, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row:
            return row
        all_users = conn.execute("SELECT * FROM users").fetchall()
        for user in all_users:
            all_names = json.loads(user['all_usernames'])
            if username in all_names:
                return user
        return None
    finally:
        conn.close()


def find_similar_messages(query_vector, top_k=5):
    import numpy as np
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT id, username, content, created_at, is_bot, is_me, vector
            FROM messages WHERE vector IS NOT NULL
            ORDER BY id DESC LIMIT 5000
        """).fetchall()
        if not rows:
            return []
        results = []
        q = query_vector / (max(float(sum(query_vector ** 2) ** 0.5), 1e-9))
        for row in rows:
            vec = np.frombuffer(row['vector'], dtype='float32')
            norm = max(float(sum(vec ** 2) ** 0.5), 1e-9)
            vec = vec / norm
            sim = float(sum(q * vec))
            results.append((sim, row))
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]
    finally:
        conn.close()


def log_bot_action(trigger_msg_id, decision, reason=None, sent_text=None, tokens=0):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO bot_log (timestamp, trigger_msg_id, decision, reason, sent_text, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (int(time.time()), trigger_msg_id, decision, reason, sent_text, tokens))
        conn.commit()
    finally:
        conn.close()


def save_correction(context, wrong, right, user_id=None):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO corrections (timestamp, context, wrong, right, user_id)
            VALUES (?, ?, ?, ?, ?)
        """, (int(time.time()), context, wrong, right, user_id))
        conn.commit()
    finally:
        conn.close()


def get_recent_corrections(limit=10):
    conn = get_conn()
    try:
        return conn.execute("""
            SELECT context, wrong, right FROM corrections
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()


def get_daily_summary_data():
    since = int(time.time()) - 86400
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE created_at > ?", (since,)
        ).fetchone()['cnt']
        bot_msgs = conn.execute("""
            SELECT content, created_at FROM messages
            WHERE is_bot=1 AND created_at > ? ORDER BY created_at ASC
        """, (since,)).fetchall()
        active_users = conn.execute("""
            SELECT username, COUNT(*) as cnt FROM messages
            WHERE created_at > ? AND is_bot=0 AND is_me=0
            GROUP BY user_id ORDER BY cnt DESC LIMIT 5
        """, (since,)).fetchall()
        return {'total_messages': total, 'bot_messages': bot_msgs, 'active_users': active_users}
    finally:
        conn.close()


def archive_old_messages():
    cutoff_warm = int(time.time()) - (WARM_LAYER_DAYS * 86400)
    cutoff_hot = int(time.time()) - (HOT_LAYER_DAYS * 86400)
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE messages SET layer='warm'
            WHERE layer='hot' AND created_at < ? AND is_bot=0 AND is_me=0
        """, (cutoff_hot,))
        deleted = conn.execute("""
            DELETE FROM messages
            WHERE layer='warm' AND created_at < ? AND is_bot=0 AND is_me=0
        """, (cutoff_warm,)).rowcount
        conn.commit()
        print("[DB] Удалено старых сообщений: {}".format(deleted))
    finally:
        conn.close()
