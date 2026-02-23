"""
ГЛАВНЫЙ ЦИКЛ БОТА
"""
import time
import random
import threading
import requests
from datetime import datetime, timezone

from config import (
    CHAT_READ_URL, CHAT_SEND_URL, CHAT_JWT_TOKEN,
    MY_USER_ID, MY_USERNAME, CHAT_MAX_LENGTH,
    CONTEXT_WINDOW, RANDOM_REPLY_CHANCE,
    MIN_REPLY_DELAY, MAX_REPLY_DELAY,
    CONTEST_START_HOUR, CONTEST_SPAM_THRESHOLD,
    ROLE_ADMIN, ROLE_MODERATOR, RAG_TOP_K,
    MY_MENTION_ALIASES, NEWS_DROP_CHANCE
)
from database import (
    save_message, get_last_messages, get_last_message_id,
    set_last_message_id, upsert_user, get_user_profile,
    log_bot_action, get_bot_sent_messages, get_recent_corrections,
    find_similar_messages, get_state, set_state, init_db
)
from embeddings import get_vector
from brain import (
    decide_should_reply, analyze_tone, search_fact,
    generate_reply, check_and_improve, generate_spontaneous_message,
    is_politics_topic, generate_politics_deflect,
    generate_mute_reaction, fetch_and_drop_news,
    generate_reaction_to_negativity
)


class BotState:
    def __init__(self):
        self.phase = get_state("phase", "observing")
        self.messages_collected = int(get_state("messages_collected", "0"))
        self.last_message_id = get_last_message_id()
        self.contest_mode = False
        self.contest_ended = False
        self.last_admin_msg_time = 0
        self.last_reply_time = 0
        self.spam_tracker = {}
        self.muted_until = 0
        self.ask_mute_reason = False
        self.last_mute_time = 0
        self.last_chat_activity = time.time()
        self.last_spontaneous = 0
        print("[STATE] Фаза: {}, сообщений: {}".format(self.phase, self.messages_collected))

    def save_phase(self):
        set_state("phase", self.phase)
        set_state("messages_collected", str(self.messages_collected))

init_db()
state = BotState()
OBSERVATION_THRESHOLD = 250
SILENCE_TRIGGER_MIN = 10 * 60
SILENCE_TRIGGER_MAX = 40 * 60
SPONTANEOUS_COOLDOWN = 20 * 60


def _is_mention_of_me(text):
    text_lower = text.lower()
    for alias in MY_MENTION_ALIASES:
        if alias.lower() in text_lower:
            return True
    return False


def _is_negative_about_me(text):
    negative_words = [
        "лох", "дурак", "идиот", "тупой", "мусор", "отстой",
        "нуб", "дно", "кринж", "позор", "слабак", "бот"
    ]
    text_lower = text.lower()
    return _is_mention_of_me(text) and any(w in text_lower for w in negative_words)


def _get_active_moderator(recent_messages):
    for msg in reversed(recent_messages):
        if msg.get("role") == ROLE_MODERATOR or msg.get("role") == ROLE_ADMIN:
            return msg.get("username", "модер")
    return "модер"


def fetch_new_messages():
    try:
        headers = {"Accept": "application/json, text/plain, */*", "Accept-Language": "ru"}
        resp = requests.get(CHAT_READ_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("messages", [])
    except Exception as e:
        print("[READER] Ошибка: {}".format(e))
        return []


def is_spam(user_id):
    now = time.time()
    if user_id not in state.spam_tracker:
        state.spam_tracker[user_id] = []
    state.spam_tracker[user_id] = [t for t in state.spam_tracker[user_id] if now - t < 60]
    state.spam_tracker[user_id].append(now)
    return len(state.spam_tracker[user_id]) >= CONTEST_SPAM_THRESHOLD


def should_skip_contest():
    return datetime.now(timezone.utc).hour == CONTEST_START_HOUR


def send_message(text):
    if state.muted_until > time.time():
        remaining = int(state.muted_until - time.time())
        print("[SENDER] Замучен ещё {}с, молчу".format(remaining))
        return

    parts = [p.strip() for p in text.split("|") if p.strip()]
    if not parts:
        return

    final_parts = []
    for part in parts:
        if len(part) <= CHAT_MAX_LENGTH:
            final_parts.append(part)
        else:
            words = part.split()
            current = ""
            for word in words:
                if len(current) + len(word) + 1 <= CHAT_MAX_LENGTH:
                    current = (current + " " + word).strip()
                else:
                    if current:
                        final_parts.append(current)
                    current = word
            if current:
                final_parts.append(current)

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": "JWT {}".format(CHAT_JWT_TOKEN),
        "Accept-Language": "ru"
    }

    for i, part in enumerate(final_parts):
        if state.muted_until > time.time():
            print("[SENDER] Замутили во время отправки, стоп")
            return
        try:
            resp = requests.post(CHAT_SEND_URL, json={"text": part}, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                resp_data = data.get("data", {})
                if resp_data.get("failed"):
                    muted_at_str = resp_data.get("mutedAt", "")
                    if muted_at_str:
                        try:
                            muted_dt = datetime.fromisoformat(muted_at_str.replace("Z", "+00:00"))
                            state.muted_until = muted_dt.timestamp()
                            state.ask_mute_reason = True
                            state.last_mute_time = time.time()
                            remaining = int(state.muted_until - time.time())
                            print("[SENDER] Замутили на {}с".format(remaining))
                        except Exception:
                            state.muted_until = time.time() + 600
                    else:
                        state.muted_until = time.time() + 300
                    return
                print("[SENDER] OK: {}".format(part))
                save_message(
                    msg_id=int(time.time() * 1000) + i,
                    user_id=MY_USER_ID, username=MY_USERNAME,
                    content=part, role=1,
                    created_at=int(time.time()),
                    vector=get_vector(part),
                    is_bot=True, is_me=False
                )
            else:
                print("[SENDER] HTTP {}".format(resp.status_code))
        except Exception as e:
            print("[SENDER] Ошибка: {}".format(e))

        if i < len(final_parts) - 1:
            time.sleep(3.0)


def process_message(msg):
    user_id = msg["user"]["id"]
    username = msg["user"]["name"]
    content = msg["content"]
    msg_id = msg["id"]

    context = get_last_messages(CONTEXT_WINDOW)
    context_for_brain = [dict(m) for m in context]

    # Политика - уходим от темы
    if is_politics_topic(content):
        if _is_mention_of_me(content) or random.random() < 0.2:
            time.sleep(random.uniform(5, 20))
            reply = generate_politics_deflect(MY_USERNAME)
            if reply:
                send_message(reply)
                state.last_reply_time = time.time()
        log_bot_action(msg_id, "politics_deflect", "тема политики")
        return

    # Негатив о нас без прямого обращения
    if _is_negative_about_me(content) and not _is_mention_of_me(content):
        time.sleep(random.uniform(8, 25))
        reply = generate_reaction_to_negativity(content, username, context_for_brain, MY_USERNAME)
        if reply:
            send_message(reply)
            state.last_reply_time = time.time()
            log_bot_action(msg_id, "negativity_reaction", "негатив от {}".format(username))
        return

    direct_mention = _is_mention_of_me(content)
    random_chance = random.random() < RANDOM_REPLY_CHANCE
    decision = decide_should_reply(
        new_message={"username": username, "content": content},
        context_messages=context_for_brain,
        my_username=MY_USERNAME,
        random_chance=random_chance
    )

    if not direct_mention and not decision.get("should_reply"):
        log_bot_action(msg_id, "ignore", decision.get("reason", ""))
        return

    if time.time() - state.last_reply_time < MIN_REPLY_DELAY and not direct_mention:
        return

    user_profile = get_user_profile(user_id)
    user_profile_dict = dict(user_profile) if user_profile else {}
    tone = analyze_tone(content, user_profile_dict)

    search_result = None
    if decision.get("needs_search"):
        search_result = search_fact(content)

    query_vec = get_vector(content)
    memory_fragments = find_similar_messages(query_vec, top_k=RAG_TOP_K)
    my_examples = get_bot_sent_messages(limit=10)
    corrections = [dict(c) for c in get_recent_corrections(limit=5)]

    reply_text = generate_reply(
        new_message={"username": username, "content": content},
        context_messages=context_for_brain,
        memory_fragments=memory_fragments,
        tone_analysis=tone,
        search_result=search_result,
        my_style_examples=[dict(m) for m in my_examples],
        corrections=corrections,
        user_profile=user_profile_dict
    )

    if not reply_text:
        return

    context_brief = " | ".join(["{}:{}".format(m['username'], m['content']) for m in context_for_brain[-5:]])
    final_reply = check_and_improve(reply_text, context_brief)

    delay = random.uniform(3, 15) if direct_mention else random.uniform(MIN_REPLY_DELAY, MAX_REPLY_DELAY)
    print("[BOT] Жду {}с...".format(int(delay)))
    time.sleep(delay)

    send_message(final_reply)
    state.last_reply_time = time.time()
    log_bot_action(msg_id, "reply" if not random_chance else "random_reply",
                   decision.get("reason"), final_reply)


def _maybe_write_spontaneous():
    if state.contest_mode or state.phase == "observing":
        return
    if state.muted_until > time.time():
        return

    now = time.time()
    silence_seconds = now - state.last_chat_activity

    threshold_str = get_state("spontaneous_threshold", "0")
    threshold = float(threshold_str)
    if threshold == 0:
        threshold = random.uniform(SILENCE_TRIGGER_MIN, SILENCE_TRIGGER_MAX)
        set_state("spontaneous_threshold", str(threshold))

    if silence_seconds < threshold:
        return
    if now - state.last_spontaneous < SPONTANEOUS_COOLDOWN:
        return
    if now - state.last_reply_time < SILENCE_TRIGGER_MIN:
        return

    silence_minutes = int(silence_seconds / 60)
    print("[BOT] Тишина {} мин, думаю написать...".format(silence_minutes))

    context = get_last_messages(10)
    context_list = [dict(m) for m in context]

    if random.random() < NEWS_DROP_CHANCE:
        text = fetch_and_drop_news(MY_USERNAME)
    else:
        text = generate_spontaneous_message(context_list, silence_minutes, MY_USERNAME)

    if text:
        delay = random.uniform(5, 30)
        time.sleep(delay)
        send_message(text)
        state.last_spontaneous = time.time()
        state.last_reply_time = time.time()

    set_state("spontaneous_threshold", "0")


def maintenance_loop():
    WEEK = 7 * 24 * 3600
    while True:
        try:
            last_run = float(get_state("last_maintenance", "0"))
            if time.time() - last_run >= WEEK:
                print("[MAINTENANCE] Запускаю обслуживание...")
                from database import archive_old_messages
                from maintenance import create_user_portraits
                archive_old_messages()
                create_user_portraits()
                set_state("last_maintenance", str(time.time()))
                print("[MAINTENANCE] Готово!")
        except Exception as e:
            print("[MAINTENANCE] Ошибка: {}".format(e))
        time.sleep(3600)


def run():

    print("[BOT] Запускаюсь как {}".format(MY_USERNAME))

    threading.Thread(target=maintenance_loop, daemon=True).start()

    while True:
        try:
            messages = fetch_new_messages()

            if not messages:
                time.sleep(3)
                continue

            max_id = max(m["id"] for m in messages)
            if state.last_message_id > max_id:
                print("[BOT] ID сбросился, начинаем заново")
                state.last_message_id = 0
                set_last_message_id(0)

            new_messages = [m for m in messages if m["id"] > state.last_message_id]

            if not new_messages:
                _maybe_write_spontaneous()
                time.sleep(1)
                continue

            for msg in new_messages:
                user_id = msg["user"]["id"]
                user_role = msg["user"]["role"]
                content = msg["content"]
                msg_type = msg.get("type", 1)

                if msg_type != 1:
                    continue

                state.last_chat_activity = time.time()

                # Проверяем размутили ли нас
                if state.ask_mute_reason and state.muted_until < time.time():
                    state.ask_mute_reason = False
                    recent = get_last_messages(20)
                    recent_list = [dict(m) for m in recent]
                    mod_name = _get_active_moderator(recent_list)
                    time.sleep(random.uniform(5, 20))
                    mute_reply = generate_mute_reaction(mod_name, MY_USERNAME)
                    if mute_reply:
                        send_message(mute_reply)
                        state.last_reply_time = time.time()

                # Логика конкурса
                if should_skip_contest() and not state.contest_mode:
                    print("[BOT] 19:00 UTC - режим конкурса")
                    state.contest_mode = True
                    state.contest_ended = False

                if state.contest_mode:
                    if user_role == ROLE_ADMIN:
                        state.contest_ended = True
                        print("[BOT] Конкурс завершён, жду открытия чата")
                    elif state.contest_ended and user_role == 1:
                        print("[BOT] Чат открыт, выхожу из режима конкурса")
                        state.contest_mode = False
                        state.contest_ended = False
                    else:
                        continue

                if is_spam(user_id):
                    continue

                is_me = (user_id == MY_USER_ID)

                vec = get_vector(content)
                save_message(
                    msg_id=msg["id"], user_id=user_id,
                    username=msg["user"]["name"], content=content,
                    role=user_role, created_at=int(time.time()),
                    vector=vec, is_bot=False, is_me=is_me
                )
                upsert_user(user_id, msg["user"]["name"], user_role)

                if state.phase == "observing":
                    state.messages_collected += 1
                    if state.messages_collected % 50 == 0:
                        state.save_phase()
                        print("[BOT] Наблюдаю... {}/{}".format(
                            state.messages_collected, OBSERVATION_THRESHOLD))
                    if state.messages_collected >= OBSERVATION_THRESHOLD:
                        state.phase = "active"
                        state.save_phase()
                        print("[BOT] Активный режим!")
                    continue

                if is_me:
                    continue

                process_message(msg)

            if new_messages:
                state.last_message_id = max(m["id"] for m in new_messages)
                set_last_message_id(state.last_message_id)

        except KeyboardInterrupt:
            print("[BOT] Остановлен")
            state.save_phase()
            break
        except Exception as e:
            print("[BOT] Ошибка: {}".format(e))
            time.sleep(5)

        time.sleep(1)


if __name__ == "__main__":
    run()
