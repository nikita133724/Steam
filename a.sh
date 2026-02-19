#!/bin/bash
set -e

MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"
NGROK_AUTHTOKEN="39sBajKz1uuDqelrLi9TzKrOLxe_53kq1Zm8nj1B7BDQ3bNNx"

export PATH="$OLLAMA_PATH:$PATH"

# 1) Установка Ollama
if ! command -v ollama &> /dev/null; then
    echo "Ollama не найден — устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

# 2) Подтягиваем модель
echo "Подтягиваем модель $MODEL..."
ollama pull $MODEL || echo "Warning: pull может падать до запуска сервера"

# 3) Запуск Ollama API
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

# 4) Отключаем репозиторий Yarn, чтобы apt update не падал
if [ -f /etc/apt/sources.list.d/yarn.list ]; then
    sudo mv /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.list.disabled
fi

# 5) Установка ngrok через apt
if ! command -v ngrok &> /dev/null; then
    echo "Добавляем ngrok репозиторий..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
      | sudo tee /etc/apt/sources.list.d/ngrok.list

    sudo apt update
    sudo apt install -y ngrok
else
    echo "ngrok уже установлен"
fi

# 6) Добавление Authtoken
echo "Добавляем ngrok authtoken..."
ngrok config add-authtoken $NGROK_AUTHTOKEN || echo "Автогок токен уже сохранён"

# 7) Запуск туннеля ngrok
echo "Запускаем ngrok..."
nohup ngrok http $PORT --traffic-policy=local > ngrok.log 2>&1 &

sleep 3
echo "ngrok запущен — см. ngrok.log"

# 8) Показ примера cURL
NGROK_URL=$(grep -o 'https://[0-9a-z]*\.ngrok\.io' ngrok.log | head -1)

echo ""
echo "Пример запроса к Ollama через ngrok:"
echo "curl $NGROK_URL/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
