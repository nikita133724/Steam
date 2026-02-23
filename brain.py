"""
МОЗГ БОТА - все запросы к Groq
"""
import time
import json
import random
import requests
from config import (
    PROXY_URL, MODEL_FAST, MODEL_SMART, MODEL_SEARCH,
    MY_USERNAME, CHAT_MAX_LENGTH, POLITICS_KEYWORDS
)



def _groq_request(model, messages, temperature=0.7, max_tokens=200, tools=None):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "stream": False,
        "stop": None
    }
    print(f"[DEBUG] Отправляю модель {model}. Payload: {json.dumps(payload, ensure_ascii=False)}")
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "required"
        
    # Пытаемся сделать запрос до 3 раз при ошибках сервера
    for attempt in range(3):
        try:
            resp = requests.post(PROXY_URL, json=payload, timeout=30)
            
            # Если поймали рейт-лимит (429) или ошибку сервера (500)
            if resp.status_code in [429, 500, 502, 503]:
                wait_time = (attempt + 1) * 5 # Ждем 5, 10... секунд
                print(f"[BRAIN] Сервер перегружен ({resp.status_code}). Жду {wait_time}с...")
                time.sleep(wait_time)
                continue
                
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            
            if tools and msg.get("tool_calls"):
                return msg["tool_calls"][0]["function"]["arguments"]
            return msg.get("content", "").strip()
            
        except Exception as e:
            if attempt == 2: # Последняя попытка
                print("[BRAIN] Ошибка после 3 попыток: {}".format(e))
                return None
            time.sleep(2)
    return None


# --- Инструменты ---

DECIDE_TOOLS = [{"type": "function", "function": {
    "name": "make_decision",
    "description": "Принять решение отвечать или нет",
    "parameters": {"type": "object", "properties": {
        "should_reply": {"type": "boolean"},
        "reason": {"type": "string"},
        "addressed_to_me": {"type": "boolean"},
        "needs_search": {"type": "boolean"}
    }, "required": ["should_reply", "reason", "addressed_to_me", "needs_search"]}
}}]

ANALYZE_TOOLS = [{"type": "function", "function": {
    "name": "analyze_message",
    "description": "Анализ тона сообщения",
    "parameters": {"type": "object", "properties": {
        "tone": {"type": "string", "enum": ["friendly", "aggressive", "sarcastic", "question", "joke", "serious", "neutral"]},
        "emotion": {"type": "string", "enum": ["happy", "angry", "sad", "excited", "bored", "neutral"]},
        "reply_style": {"type": "string", "enum": ["friendly", "sarcastic", "aggressive", "short", "joke", "ignore_aggression"]}
    }, "required": ["tone", "emotion", "reply_style"]}
}}]

CHECK_TOOLS = [{"type": "function", "function": {
    "name": "check_humanness",
    "description": "Проверить звучит ли как человек",
    "parameters": {"type": "object", "properties": {
        "sounds_human": {"type": "boolean"},
        "bot_signals": {"type": "array", "items": {"type": "string"}},
        "improved_text": {"type": "string"}
    }, "required": ["sounds_human", "bot_signals", "improved_text"]}
}}]

SPONTANEOUS_TOOLS = [{"type": "function", "function": {
    "name": "spontaneous_message",
    "description": "Придумать что написать в чат от себя",
    "parameters": {"type": "object", "properties": {
        "should_write": {"type": "boolean"},
        "text": {"type": "string"},
        "reason": {"type": "string"}
    }, "required": ["should_write", "text", "reason"]}
}}]


def is_politics_topic(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in POLITICS_KEYWORDS)


#def decide_should_reply(new_message, context_messages, my_username, random_chance=False):
    # Создаем список сообщений (messages), который требует функция _groq_request
    prompt_messages = [
        {"role": "system", "content": f"Ты — фильтр внимания для пользователя {my_username}."},
        {"role": "user", "content": f"Реши, нужно ли отвечать на это: '{new_message['content']}'"}
    ]
    
    # ПЕРЕДАЕМ prompt_messages вторым аргументом
    result_str = _groq_request(MODEL_SEARCH, prompt_messages, tools=DECIDE_TOOLS)
    
    if not result_str:
        return {"should_reply": False, "reason": "api_error"}
        
    try:
        data = json.loads(result_str)
        if isinstance(data, dict):
            return data
        return {"should_reply": bool(data), "reason": "simple_bool"}
    except Exception:
        return {"should_reply": False, "reason": "parse_error"}


def decide_should_reply(new_message, context_messages, my_username, random_chance=False):
    # Добавляем СТРОГОЕ указание по типам данных
    prompt_messages = [
        {"role": "system", "content": (
            f"Ты — фильтр внимания для пользователя {my_username}. "
            "Отвечай ТОЛЬКО через инструмент make_decision. "
            "ВАЖНО: Поля should_reply, addressed_to_me и needs_search должны быть BOOLEAN (true/false без кавычек). "
            "НЕ пиши их как строки."
        )},
        {"role": "user", "content": f"Реши, нужно ли отвечать на это: '{new_message['content']}'"}
    ]
    
    result_str = _groq_request(MODEL_SEARCH, prompt_messages, tools=DECIDE_TOOLS)
    
    if not result_str:
        return {"should_reply": False, "reason": "api_error"}
        
    try:
        data = json.loads(result_str)
        if isinstance(data, dict):
            # "Мягкое" исправление: если модель прислала строку "false" вместо False
            for key in ["should_reply", "addressed_to_me", "needs_search"]:
                if key in data and isinstance(data[key], str):
                    data[key] = data[key].lower() == "true"
            return data
        return {"should_reply": bool(data), "reason": "simple_bool"}
    except Exception:
        return {"should_reply": False, "reason": "parse_error"}


def analyze_tone(message_content, user_profile=None):
    user_info = ""
    if user_profile:
        user_info = "Отношения: {}. Заметки: {}.".format(
            user_profile.get('relationship', 'neutral'),
            user_profile.get('notes', 'нет')
        )
    result_str = _groq_request(
        MODEL_FAST,
        [{"role": "user", "content": "Проанализируй тон: '{}'. {}".format(message_content, user_info)}],
        temperature=0.1, max_tokens=80, tools=ANALYZE_TOOLS
    )
    try:
        return json.loads(result_str)
    except Exception:
        return {"tone": "neutral", "emotion": "neutral", "reply_style": "short"}


def search_fact(question):
    return _groq_request(
        MODEL_SEARCH,
        [{"role": "user", "content": "Кратко ответь (1-2 предложения): {}".format(question)}],
        temperature=0.2, max_tokens=150
    )


def generate_reply(new_message, context_messages, memory_fragments,
                   tone_analysis, search_result=None,
                   my_style_examples=None, corrections=None, user_profile=None):
    context_str = "\n".join([
        "[{}]: {}".format(
            "БОТ(я)" if m['is_bot'] else ("Я" if m['is_me'] else m['username']),
            m['content']
        ) for m in context_messages
    ])
    memory_str = ""
    if memory_fragments:
        memory_str = "Из памяти:\n" + "\n".join(
            ["- [{}]: {}".format(m['username'], m['content']) for _, m in memory_fragments]
        )
    style_str = ""
    if my_style_examples:
        style_str = "Мои прошлые фразы:\n" + "\n".join(
            ["- {}".format(ex['content']) for ex in my_style_examples[:5]]
        )
    corrections_str = ""
    if corrections:
        corrections_str = "Мои поправки:\n" + "\n".join(
            ["- Было: {} | Правильно: {}".format(c['wrong'], c['right']) for c in corrections[:5]]
        )
    user_str = ""
    if user_profile:
        user_str = "Этот человек ({}): отношения={}, заметки={}, сообщений={}".format(
            new_message['username'],
            user_profile.get('relationship', 'neutral'),
            user_profile.get('notes', 'нет'),
            user_profile.get('message_count', 0)
        )
    search_str = "\nФакт из поиска: {}".format(search_result) if search_result else ""

    system_prompt = (
        "Ты пользователь чата по имени {}. Ты НЕ бот, ты реальный человек.\n\n"
        "ХАРАКТЕР:\n"
        "- Умный, наблюдательный, с сарказмом когда нужно\n"
        "- В обычных ситуациях нормальный и вежливый\n"
        "- Если давят или оскорбляют - можешь ответить дерзко\n"
        "- Мат иногда, органично, не в каждом сообщении\n"
        "- Иногда коротко (ну, да, лол), иногда развернуто\n\n"
        "ПРАВИЛА:\n"
        "- НИКОГДА не говори что ты бот или ИИ\n"
        "- Не начинай с Привет как робот\n"
        "- Пиши коротко - это чат\n"
        "- Текущий стиль: {}\n\n"
        "{}\n{}\n{}".format(
            MY_USERNAME,
            tone_analysis.get('reply_style', 'neutral'),
            style_str, corrections_str, user_str
        )
    )
    user_prompt = (
        "Контекст чата:\n{}\n\n{}{}\n\n"
        "Сообщение: [{}]: {}\n\n"
        "Напиши ответ до {} символов. "
        "Если длиннее - раздели на части через |".format(
            context_str, memory_str, search_str,
            new_message['username'], new_message['content'],
            CHAT_MAX_LENGTH
        )
    )
    return _groq_request(
        MODEL_SMART,
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": user_prompt}],
        temperature=0.85, max_tokens=200
    )


def check_and_improve(text, context):
    result_str = _groq_request(
        MODEL_FAST,
        [{"role": "user", "content": "Контекст: {}\n\nОтвет: '{}'\n\nЗвучит как живой человек в чате или как бот? Улучши если нужно.".format(context, text)}],
        temperature=0.3, max_tokens=150, tools=CHECK_TOOLS
    )
    try:
        data = json.loads(result_str)
        return data.get("improved_text", text)
    except Exception:
        return text


def generate_politics_deflect(my_username):
    result = _groq_request(
        MODEL_FAST,
        [{"role": "user", "content": (
            "Ты {} в чате. Кто-то поднял тему политики. "
            "Напиши короткий ответ (до 90 символов) что ты к политике нейтрален, "
            "ко всем странам и народам относишься одинаково. Неформально.".format(my_username)
        )}],
        temperature=0.7, max_tokens=80
    )
    return result or "я вне политики, ко всем норм отношусь"


def generate_mute_reaction(moderator_name, my_username):
    result = _groq_request(
        MODEL_FAST,
        [{"role": "user", "content": (
            "Ты {} в чате. Тебя только что размутили. "
            "Модератор: {}. Напиши вопрос за что дали мут (до 90 символов). "
            "Можно с лёгким матом, с возмущением. Как живой человек.".format(
                my_username, moderator_name)
        )}],
        temperature=0.85, max_tokens=80
    )
    return result or "{}, за что мут то дали?".format(moderator_name)


def generate_reaction_to_negativity(bad_message, author, context_messages, my_username):
    context_str = "\n".join(["[{}]: {}".format(m['username'], m['content'])
                              for m in context_messages[-8:]])
    return _groq_request(
        MODEL_SMART,
        [
            {"role": "system", "content": (
                "Ты {} - реальный человек в чате, не бот. "
                "Кто-то написал про тебя нехорошее не обращаясь напрямую. "
                "Ты заметил и отвечаешь. Дерзко но умно. Сарказм, мат в меру. До 90 символов.".format(my_username)
            )},
            {"role": "user", "content": "Контекст:\n{}\n\n{} написал: '{}'\n\nТвой ответ:".format(
                context_str, author, bad_message)}
        ],
        temperature=0.9, max_tokens=100
    )


def generate_spontaneous_message(last_messages, silence_minutes, my_username):
    context_str = "\n".join(["[{}]: {}".format(m['username'], m['content'])
                              for m in last_messages[-10:]]) if last_messages else "Чат пустой"
    prompt = (
        "Ты {} - живой участник чата. Тишина уже {} минут.\n\n"
        "Последние сообщения:\n{}\n\n"
        "Стоит ли написать что-нибудь? Если да - придумай что. "
        "Это может быть комментарий, вброс, шутка, наблюдение, вопрос. "
        "Коротко. Иногда лучше промолчать.".format(my_username, silence_minutes, context_str)
    )
    result_str = _groq_request(
        MODEL_SMART,
        [{"role": "user", "content": prompt}],
        temperature=0.95, max_tokens=120, tools=SPONTANEOUS_TOOLS
    )
    try:
        data = json.loads(result_str)
        if data.get("should_write") and data.get("text"):
            return data["text"]
        return None
    except Exception:
        return None


def fetch_and_drop_news(my_username):
    topics = [
        "CS2 новость сегодня",
        "CS2 обновление патч",
        "киберспорт турнир CS2 результаты",
        "Dota 2 новость сегодня",
        "скины CS2 цены новость",
        "FACEIT ESL турнир результат",
        "интересная мировая новость сегодня не политика",
        "технологии игры новость сегодня"
    ]
    topic = random.choice(topics)
    news = _groq_request(
        MODEL_SEARCH,
        [{"role": "user", "content": (
            "Найди свежую новость по теме: {}. "
            "Только факт, одно предложение. Без политики. "
            "Если нет - напиши None.".format(topic)
        )}],
        temperature=0.2, max_tokens=120
    )
    if not news or "none" in news.lower() or len(news) < 10:
        return None
    result = _groq_request(
        MODEL_FAST,
        [{"role": "user", "content": (
            "Ты {} в чате геймеров. Только что узнал: {}\n"
            "Напиши в чат как живой человек (до 90 символов). "
            "Неформально, можно с реакцией. Не начинай с Привет.".format(my_username, news)
        )}],
        temperature=0.9, max_tokens=80
    )
    return result


def generate_daily_summary(data):
    bot_msgs_str = "\n".join(["- {}".format(m['content']) for m in data['bot_messages']]) if data['bot_messages'] else "ничего не писал"
    active_str = "\n".join(["- {}: {} сообщений".format(u['username'], u['cnt']) for u in data['active_users']])
    prompt = (
        "Составь краткий отчёт (5-10 предложений) о чате за 24 часа.\n\n"
        "Всего сообщений: {}\nАктивные:\n{}\nЧто писал бот:\n{}\n\n"
        "От первого лица, неформально, кратко.".format(
            data['total_messages'], active_str, bot_msgs_str)
    )
    return _groq_request(MODEL_SMART, [{"role": "user", "content": prompt}],
                          temperature=0.5, max_tokens=500)


def generate_user_portrait(user_messages, username):
    msgs_str = "\n".join(["- {}".format(m) for m in user_messages[:100]])
    prompt = (
        "Сообщения пользователя {} из чата:\n{}\n\n"
        "Напиши краткий портрет (3-5 предложений): как общается, "
        "что любит обсуждать, характер, конфликты. Для долгосрочной памяти.".format(username, msgs_str)
    )
    return _groq_request(MODEL_FAST, [{"role": "user", "content": prompt}],
                          temperature=0.3, max_tokens=200)
