#!/bin/bash
set -e

MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"
NGROK_AUTHTOKEN="39sBajKz1uuDqelrLi9TzKrOLxe_53kq1Zm8nj1B7BDQ3bNNx"

export PATH="$OLLAMA_PATH:$PATH"

# ---------------------------
# 0) Проверяем jq
# ---------------------------
if ! command -v jq &> /dev/null; then
    echo "jq не найден — ставим..."
    sudo apt update
    sudo apt install -y jq
fi

# ---------------------------
# 1) Установка Ollama
# ---------------------------
if ! command -v ollama &> /dev/null; then
    echo "Ollama не найден — устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

# ---------------------------
# 2) Подтягиваем модель
# ---------------------------
echo "Подтягиваем модель $MODEL..."
ollama pull $MODEL || echo "Warning: pull может падать до запуска сервера"

# ---------------------------
# 3) Запуск Ollama API
# ---------------------------
echo "Запускаем Ollama API..."
nohup ollama serve > ollama.log 2>&1 &

echo "Ждём Ollama сервер..."
for i in {1..10}; do
    if curl -s http://127.0.0.1:$PORT/v1/models > /dev/null; then
        echo "Ollama сервер готов!"
        break
    fi
    sleep 1
done

# ---------------------------
# 4) Отключаем Yarn репозиторий, чтобы apt update не падал
# ---------------------------
if [ -f /etc/apt/sources.list.d/yarn.list ]; then
    sudo mv /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.list.disabled
fi

# ---------------------------
# 5) Установка ngrok
# ---------------------------
if ! command -v ngrok &> /dev/null; then
    echo "Устанавливаем ngrok..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
      | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt update
    sudo apt install -y ngrok
else
    echo "ngrok уже установлен"
fi

# ---------------------------
# 6) Добавление токена ngrok
# ---------------------------
echo "Добавляем ngrok authtoken..."
ngrok config add-authtoken $NGROK_AUTHTOKEN || echo "Authtoken уже добавлен"

# ---------------------------
# 7) Запуск туннеля ngrok
# ---------------------------
echo "Запускаем ngrok туннель..."
nohup ngrok http $PORT > /dev/null 2>&1 &

# Ждём, пока ngrok полностью стартует
echo "Ждём запуска ngrok..."
sleep 5

# Получаем публичный URL через ngrok API
NGROK_URL=$(ngrok api tunnels list --json | jq -r '.tunnels[0].public_url')

if [ -z "$NGROK_URL" ] || [ "$NGROK_URL" == "null" ]; then
    echo "Ошибка: не удалось получить публичный URL ngrok"
    exit 1
fi

echo "ngrok запущен! Публичный URL: $NGROK_URL"

# ---------------------------
# 8) Пример cURL запроса
# ---------------------------
echo ""
echo "Пример запроса к Ollama через ngrok:"
echo "curl $NGROK_URL/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
