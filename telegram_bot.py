"""
TELEGRAM БОТ - панель управления
"""
import time
import threading
import requests
from database import (
    get_daily_summary_data, save_correction,
    update_user_notes, get_user_by_username
)
from brain import generate_daily_summary
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_MY_ID

TG_API = "https://api.telegram.org/bot{}".format(TELEGRAM_BOT_TOKEN)
_last_update_id = 0


def tg_send(chat_id, text):
    try:
        requests.post("{}/sendMessage".format(TG_API),
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        print("[TG] Ошибка: {}".format(e))


def tg_get_updates():
    global _last_update_id
    try:
        resp = requests.get("{}/getUpdates".format(TG_API),
                            params={"offset": _last_update_id + 1, "timeout": 10},
                            timeout=15)
        return resp.json().get("result", [])
    except Exception:
        return []


def handle_command(chat_id, text):
    text = text.strip()

    if text.lower() == "/help":
        help_text = (
            "<b>🤖 Справка по управлению Сахарком</b>\n\n"
            "<b>📊 Инфо и отчёты:</b>\n"
            "• <code>отчёт</code> или <code>расскажи</code> — сводка событий в чате за 24 часа.\n"
            "• <code>статус</code> — текущая фаза бота (обучение/актив).\n\n"
            "<b>👤 Управление игроками:</b>\n"
            "• <code>/user [ник]</code> — посмотреть досье на игрока.\n"
            "• <code>/note [ник] [текст]</code> — <b>Важное!</b> Записать инструкцию, как боту относиться к человеку. "
                "<i>Пример: /note ivan Друг, общайся вежливо.</i>\n\n"
            "<b>🧠 Обучение и исправление:</b>\n"
            "• <code>/fix [текст]</code> — если бот тупанул в чате, напиши сюда, как надо было ответить. Он запомнит это как пример.\n\n"
            "<b>💬 Общение:</b>\n"
            "• Просто пиши любой текст без команд, чтобы поболтать со мной напрямую."
        )
        tg_send(chat_id, help_text)
        return

    if text.lower() in ["/summary", "что было", "расскажи", "отчёт"]:
        tg_send(chat_id, "Генерирую отчёт...")
        data = get_daily_summary_data()
        summary = generate_daily_summary(data)
        tg_send(chat_id, "<b>За последние 24 часа:</b>\n\n{}".format(summary))
        return

    # Команда /user [ID]
    if text.lower().startswith("/user "):
        user_id = text[6:].strip()
        from database import get_user_profile
        
        user = get_user_profile(user_id) # Используем готовую функцию из database.py
        if user:
            # Твой существующий код вывода инфо
            info = "👤 <b>Игрок:</b> {}\n🆔 <b>ID:</b> {}\n📝 <b>Заметка:</b> {}".format(
                user['username'], user['user_id'], user.get('notes', 'Нет')
            )
            tg_send(chat_id, info)
        else:
            tg_send(chat_id, "Пользователь с ID {} не найден.".format(user_id))
        return

    # Команда /note [ID] [текст]
    if text.lower().startswith("/note "):
        parts = text.split(maxsplit=2)
        if len(parts) == 3:
            target_id = parts[1]
            note_text = parts[2]
            from database import update_user_notes
            update_user_notes(target_id, note_text)
            tg_send(chat_id, "✅ Заметка для ID {} сохранена".format(target_id))
        else:
            tg_send(chat_id, "⚠️ Формат: /note [ID] [текст заметки]")
        return



    if text.lower().startswith("/wrong "):
        content = text[7:].strip()
        if "|" in content:
            wrong, right = content.split("|", 1)
            save_correction("через Telegram", wrong.strip(), right.strip())
            tg_send(chat_id, "Поправка сохранена, буду учитывать")
        else:
            tg_send(chat_id, "Формат: /wrong неправильное | правильное")
        return

    if text.lower() in ["/start", "/help", "помощь"]:
        tg_send(chat_id, (
            "<b>Команды:</b>\n\n"
            "/summary - отчёт за 24 часа\n"
            "/user никнейм - профиль пользователя\n"
            "/note никнейм текст - заметка о пользователе\n"
            "/wrong неправильно | правильно - поправить бота"
        ))
        return

    from brain import _groq_request, MODEL_SMART
    data = get_daily_summary_data()
    bot_msgs = [m['content'] for m in data['bot_messages']]
    context = "Последние действия: {}".format("; ".join(bot_msgs[-5:])) if bot_msgs else "Бот молчал"
    answer = _groq_request(
        MODEL_SMART,
        [{"role": "system", "content": "Ты бот управляющий чатом. Отвечай кратко и по делу."},
         {"role": "user", "content": "{}\n\nВопрос: {}".format(context, text)}],
        temperature=0.5, max_tokens=400
    )
    tg_send(chat_id, answer or "Не смог ответить")


def telegram_loop():
    global _last_update_id
    print("[TG] Telegram бот запущен")
    while True:
        try:
            updates = tg_get_updates()
            for update in updates:
                _last_update_id = update["update_id"]
                msg = update.get("message")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                user_id = msg["from"]["id"]
                if TELEGRAM_MY_ID != 0 and user_id != TELEGRAM_MY_ID:
                    tg_send(chat_id, "Нет доступа")
                    continue
                text = msg.get("text", "")
                if text:
                    handle_command(chat_id, text)
        except Exception as e:
            print("[TG] Ошибка: {}".format(e))
            time.sleep(5)
        time.sleep(1)


def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN or "ВСТАВЬ" in TELEGRAM_BOT_TOKEN:
        print("[TG] Токен не задан, Telegram отключён")
        return
    threading.Thread(target=telegram_loop, daemon=True).start()
