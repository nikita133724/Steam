#!/bin/bash

set -e

# ---------------------------
# Переменные
# ---------------------------
MODEL="llama3.2:3b"
NGROK_AUTHTOKEN="39ld8AoprRvDifymsvZdx1zriMf_FmTGhHjfQPidQfVRoAjw"
OLLAMA_PATH="$HOME/.ollama/bin"
PORT=11434

# ---------------------------
# 1. Установка Ollama
# ---------------------------
if ! command -v ollama &> /dev/null
then
    echo "Ollama не найден, устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

export PATH="$OLLAMA_PATH:$PATH"

# ---------------------------
# 2. Скачиваем модель
# ---------------------------
echo "Подтягиваем модель $MODEL..."
ollama pull $MODEL

# ---------------------------
# 3. Запуск Ollama API
# ---------------------------
echo "Запускаем Ollama API на localhost:$PORT..."
nohup ollama serve > ollama.log 2>&1 &

sleep 2
echo "Ollama API запущен. Логи в ollama.log"

# ---------------------------
# 4. Установка ngrok если нужно
# ---------------------------
if ! command -v ngrok &> /dev/null
then
    echo "ngrok не найден, устанавливаем..."
    curl -fsSL https://ngrok.com/download -o ngrok.zip
    unzip -o ngrok.zip
    chmod +x ngrok
    mv ngrok /usr/local/bin/
else
    echo "ngrok уже установлен"
fi

# ---------------------------
# 5. Конфиг ngrok
# ---------------------------
ngrok config add-authtoken $NGROK_AUTHTOKEN || echo "ngrok токен уже добавлен"

# ---------------------------
# 6. Запуск ngrok туннеля
# ---------------------------
echo "Запускаем ngrok на localhost:$PORT..."
nohup ngrok http $PORT --host-header="localhost:$PORT" > ngrok.log 2>&1 &

sleep 2
echo "ngrok запущен. Публичный адрес смотри в ngrok.log"

# ---------------------------
# 7. Пример cURL
# ---------------------------
echo ""
echo "Пример запроса к Ollama через cURL:"
echo "curl https://<твоя_ngrok_url>.ngrok.app/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
