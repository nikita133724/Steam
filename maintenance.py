"""
ЕЖЕНЕДЕЛЬНОЕ ОБСЛУЖИВАНИЕ - запускается автоматически из bot.py
"""
import time
from database import init_db, archive_old_messages, get_conn
from brain import generate_user_portrait


def create_user_portraits():
    cutoff = int(time.time()) - (30 * 86400)
    conn = get_conn()
    try:
        users = conn.execute("""
            SELECT DISTINCT u.user_id, u.username
            FROM users u
            JOIN messages m ON u.user_id = m.user_id
            WHERE u.portrait = '' AND m.created_at < ?
        """, (cutoff,)).fetchall()
        print("[MAINTENANCE] Портреты для {} пользователей".format(len(users)))
        for user in users:
            msgs = conn.execute("""
                SELECT content FROM messages
                WHERE user_id=? AND is_bot=0 AND is_me=0
                AND created_at < ? ORDER BY created_at DESC LIMIT 100
            """, (user['user_id'], cutoff)).fetchall()
            if len(msgs) < 10:
                continue
            portrait = generate_user_portrait([m['content'] for m in msgs], user['username'])
            if portrait:
                conn.execute("UPDATE users SET portrait=? WHERE user_id=?",
                             (portrait, user['user_id']))
                conn.commit()
                print("[MAINTENANCE] Портрет: {}".format(user['username']))
                time.sleep(2)
    finally:
        conn.close()


if __name__ == "__main__":
    print("[MAINTENANCE] Запуск...")
    init_db()
    archive_old_messages()
    create_user_portraits()
    print("[MAINTENANCE] Готово!")
