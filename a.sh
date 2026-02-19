#!/bin/bash
set -e

# ---------------------------
# Настройки
# ---------------------------
MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"
NGROK_PATH="/usr/local/bin"   # для apt установки ngrok
NGROK_AUTHTOKEN="39sBajKz1uuDqelrLi9TzKrOLxe_53kq1Zm8nj1B7BDQ3bNNx"

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
# 2. Подтягиваем модель
# ---------------------------
echo "Подтягиваем модель $MODEL..."
ollama pull $MODEL || echo "Warning: pull может падать если сервер ещё не поднят"

# ---------------------------
# 3. Запуск Ollama API
# ---------------------------
echo "Запускаем Ollama API на localhost:$PORT..."
nohup ollama serve > ollama.log 2>&1 &

# Ждём сервер (до 10 секунд)
echo "Ждём поднятия Ollama сервера..."
for i in {1..10}; do
    if curl -s http://127.0.0.1:$PORT/v1/models > /dev/null; then
        echo "Ollama сервер готов!"
        break
    fi
    sleep 1
done

# ---------------------------
# 4. Установка ngrok 3.x через apt
# ---------------------------
if ! command -v ngrok &> /dev/null; then
    echo "ngrok не найден, устанавливаем..."

    # Исправляем ошибку с подписью Yarn (иначе apt update прервётся)
    echo "Добавляем публичный ключ Yarn для APT..."
    curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/yarn.gpg

    # Обновляем список пакетов после добавления ключа
    sudo apt update

    # Ставим ngrok
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
# 5. Добавляем токен (один раз)
# ---------------------------
ngrok config add-authtoken $NGROK_AUTHTOKEN || echo "ngrok токен уже добавлен"

# ---------------------------
# 6. Запуск ngrok туннеля
# ---------------------------
echo "Запускаем ngrok на localhost:$PORT..."
nohup ngrok http $PORT --host-header="localhost:$PORT" > ngrok.log 2>&1 &

sleep 3
echo "ngrok запущен. Публичный адрес смотри в ngrok.log"

# ---------------------------
# 7. Пример cURL запроса
# ---------------------------
NGROK_URL=$(grep -o 'https://[0-9a-z]*\.ngrok\.io' ngrok.log | head -1)

echo ""
echo "Пример запроса к Ollama через cURL:"
echo "curl $NGROK_URL/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
