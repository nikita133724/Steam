#!/bin/bash
set -e

MODEL="llama3.2:3b"
NGROK_AUTHTOKEN="39sBajKz1uuDqelrLi9TzKrOLxe_53kq1Zm8nj1B7BDQ3bNNx"
OLLAMA_PATH="$HOME/.ollama/bin"
NGROK_PATH="$HOME/.ngrok/bin"
PORT=11434

export PATH="$OLLAMA_PATH:$NGROK_PATH:$PATH"

# ---------------------------
# 1. Установка Ollama
# ---------------------------
if ! command -v ollama &> /dev/null; then
    echo "Ollama не найден, устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

# ---------------------------
# 2. Установка ngrok 2.x
# ---------------------------
if ! command -v ngrok &> /dev/null; then
    echo "ngrok не найден, устанавливаем..."
    mkdir -p "$NGROK_PATH"
    curl -fsSL https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-linux-amd64.zip -o ngrok.zip
    unzip -o ngrok.zip -d "$NGROK_PATH"
    chmod +x "$NGROK_PATH/ngrok"
    echo "ngrok установлен в $NGROK_PATH"
else
    echo "ngrok уже установлен"
fi

# ---------------------------
# 3. Подтягиваем модель
# ---------------------------
echo "Подтягиваем модель $MODEL..."
ollama pull $MODEL || echo "Warning: pull может падать если сервер ещё не поднят"

# ---------------------------
# 4. Запуск Ollama API
# ---------------------------
echo "Запускаем Ollama API на localhost:$PORT..."
nohup ollama serve > ollama.log 2>&1 &

# Ждём сервер (проверяем до 10 секунд)
echo "Ждём поднятия Ollama сервера..."
for i in {1..10}; do
    if curl -s http://127.0.0.1:$PORT/v1/models > /dev/null; then
        echo "Ollama сервер готов!"
        break
    fi
    sleep 1
done

# ---------------------------
# 5. Запуск ngrok с токеном через переменную окружения
# ---------------------------
echo "Запускаем ngrok на localhost:$PORT..."
export NGROK_AUTHTOKEN
nohup ngrok http $PORT --host-header="localhost:$PORT" > ngrok.log 2>&1 &

sleep 3
echo "ngrok запущен. Публичный адрес смотри в ngrok.log"

# ---------------------------
# 6. Пример cURL
# ---------------------------
echo ""
echo "Пример запроса к Ollama через cURL:"
echo "curl https://<твоя_ngrok_url>.ngrok.app/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
