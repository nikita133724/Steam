# КОНФИГ БОТА САХАРОК

# --- ТВОИ ДАННЫЕ ---
MY_USER_ID = 186861
MY_USERNAME = "₡₳Х₳₱Ǿ₭" 

# JWT токен для отправки сообщений
CHAT_JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTg2ODYxLCJpYXQiOjE3NzE3NzU0MDcsImV4cCI6MTc3MjYzOTQwN30.4xWldrThVI4WKGLFjTai1kjTA5O3ar9LAnew2bvvWr8"

# --- ПРОКСИ СЕРВЕР ---
PROXY_URL = "https://rafflesrun.onrender.com/groq"

# --- GROQ МОДЕЛИ ---
MODEL_FAST = "llama-3.1-8b-instant"
MODEL_SMART = "openai/gpt-oss-20b"
MODEL_SEARCH = "Meta-llama/llama-4-scout-17b-16e-instruct"

# --- ЧАТ САЙТА ---
CHAT_READ_URL = "https://cs2run.app/chat/ru/all"
CHAT_SEND_URL = "https://cs2run.app/chat/ru"
CHAT_POLL_INTERVAL = 1
CHAT_MAX_LENGTH = 100

# --- РОЛИ В ЧАТЕ ---
ROLE_USER = 1
ROLE_MODERATOR = 5
ROLE_ADMIN = 6

# --- КОНКУРС ---
CONTEST_START_HOUR = 19
CONTEST_SPAM_THRESHOLD = 10

# --- ПОВЕДЕНИЕ БОТА ---
RANDOM_REPLY_CHANCE = 0.50
MIN_REPLY_DELAY = 8
MAX_REPLY_DELAY = 30
CONTEXT_WINDOW = 50

# --- БАЗА ДАННЫХ ---
DB_PATH = "saharok_memory.db"

# --- ПАМЯТЬ ---
HOT_LAYER_DAYS = 7
WARM_LAYER_DAYS = 60
RAG_TOP_K = 5

# --- TELEGRAM БОТ ---
TELEGRAM_BOT_TOKEN = "8253635387:AAEG2cwFTsbkDPndnSMpmTcP7_VOmE49P3Q"
TELEGRAM_MY_ID = 754274025

# --- ПОЛИТИКА ---
POLITICS_KEYWORDS = [
    "путин", "байден", "зеленский", "война", "украина", "россия",
    "нато", "сво", "мобилизация", "санкции", "политик", "президент",
    "выборы", "депутат", "кремль", "госдума", "сша", "пентагон",
    "израиль", "хамас", "палестина", "иран", "трамп", "мигрант"
]

# --- МОИ УПОМИНАНИЯ ---
# Важно: специальный ник хранится отдельно как unicode строка
MY_NICK_UNICODE = "\u20a1\u20b3\u0425\u20b3\u20a1\u01fe\u20ad"  # ₡₳Х₳₱Ǿ₭
MY_MENTION_ALIASES = [
    "сахарок", "сахар", "сахарку", "сахарка", "saharok", "sahar",
    "saxarok", MY_NICK_UNICODE, "@" + "\u20a1\u20b3\u0425\u20b3\u20a1\u01fe\u20ad"
]

# --- НОВОСТИ ---
NEWS_DROP_CHANCE = 0.03

# --- ЭМБЕДДИНГ МОДЕЛЬ ---
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
