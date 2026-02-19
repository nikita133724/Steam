#!/bin/bash
set -e

MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"

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

# 4) Отключаем Yarn репозиторий (чтобы apt update не падал)
if [ -f /etc/apt/sources.list.d/yarn.list ]; then
    sudo mv /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.list.disabled
fi

# 5) Установка ngrok
if ! command -v ngrok &> /dev/null; then
    echo "Устанавливаем ngrok 3.x..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt update
    sudo apt install -y ngrok
else
    echo "ngrok уже установлен"
fi

# 6) Запуск публичного туннеля (без токена)
echo "Запускаем публичный ngrok туннель..."
nohup ngrok http $PORT > ngrok.log 2>&1 &

# 7) Ждём 5 секунд и показываем лог
sleep 5
echo "ngrok запущен, смотри URL в ngrok.log"
echo "Пример команды для проверки URL:"
grep -o 'https://[0-9a-z]*\.ngrok\.io' ngrok.log || echo "URL пока не появился — подожди пару секунд и проверь снова"

# 8) Пример cURL запроса (подставь URL из лога)
echo ""
echo "curl https://<твоя_ngrok_url>.ngrok.io/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет, Ollama!\"}]}'"
