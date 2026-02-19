#!/bin/bash
set -e

MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"
NGROK_AUTHTOKEN="39sBajKz1uuDqelrLi9TzKrOLxe_53kq1Zm8nj1B7BDQ3bNNx"
NGROK_USER="user"          # придумай любое имя
NGROK_PASSWORD="pass123"   # придумай пароль

export PATH="$OLLAMA_PATH:$PATH"

# ---------------------------
# 1) Проверка Ollama
# ---------------------------
if ! command -v ollama &> /dev/null; then
    echo "Ollama не найден — устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

# ---------------------------
# 2) Модель уже подтянута
# ---------------------------
echo "Используем модель $MODEL (предполагается, что pull уже сделан)"

# ---------------------------
# 3) Запуск Ollama API в фоне
# ---------------------------
echo "Запускаем Ollama API..."
nohup ollama serve > ollama.log 2>&1 &
sleep 3
echo "Ollama сервер запущен на localhost:$PORT"

# ---------------------------
# 4) Установка ngrok, если нужно
# ---------------------------
if ! command -v ngrok &> /dev/null; then
    echo "Устанавливаем ngrok..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt update
    sudo apt install -y ngrok
else
    echo "ngrok уже установлен"
fi

# ---------------------------
# 5) Добавление токена ngrok
# ---------------------------
ngrok config add-authtoken $NGROK_AUTHTOKEN || echo "Authtoken уже добавлен"

# ---------------------------
# 6) Запуск публичного туннеля с basic auth
# ---------------------------
echo "Запускаем публичный туннель ngrok с авторизацией..."
nohup ngrok http $PORT --auth="$NGROK_USER:$NGROK_PASSWORD" > ngrok.log 2>&1 &
sleep 5

# ---------------------------
# 7) Получаем публичный URL
# ---------------------------
NGROK_URL=$(ngrok api tunnels list --json | jq -r '.tunnels[0].public_url')
echo "ngrok запущен! Публичный URL: $NGROK_URL"

# ---------------------------
# 8) Пример запроса cURL с базовой авторизацией
# ---------------------------
echo ""
echo "Пример запроса к Ollama через ngrok:"
echo "curl -u \"$NGROK_USER:$NGROK_PASSWORD\" \\"
echo "  -X POST \"$NGROK_URL/v1/chat/completions\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
