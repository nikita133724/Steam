#!/bin/bash
set -e

# ---------------------------
# Настройки
# ---------------------------
MODEL="llama3.2:7b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"

export PATH="$OLLAMA_PATH:$PATH"

# ---------------------------
# 0) Очищаем старые процессы
# ---------------------------
echo "Убиваем старый сервер Ollama, если есть..."
pkill -f "ollama serve" || true

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
# 2) Запуск сервера Ollama
# ---------------------------
export OLLAMA_HOST=0.0.0.0
export OLLAMA_PORT=$PORT

echo "Запускаем Ollama API на $OLLAMA_HOST:$PORT..."
nohup ollama serve > ollama.log 2>&1 &

# ---------------------------
# 3) Ждём старта сервера
# ---------------------------
echo "Ждём 5–10 секунд, пока сервер поднимется..."
sleep 7

echo "Проверяем локально..."
curl -s http://127.0.0.1:$PORT/v1/models || echo "Сервер ещё не готов"

# ---------------------------
# 4) Проверяем модель и подтягиваем, если нужно
# ---------------------------
if ! ollama list | grep -q "$MODEL"; then
    echo "Модель $MODEL не найдена, подтягиваем..."
    ollama pull $MODEL
else
    echo "Модель $MODEL уже есть"
fi

# ---------------------------
# 5) Показ публичного URL Codespaces
# ---------------------------
echo ""
echo "Теперь зайди в Codespaces → Ports → 11434 → Visibility → Public"
echo ""
echo "Твой публичный URL будет вида:"
echo "https://<твое-имя>-11434.app.github.dev"
echo ""
echo "Пример запроса к Ollama через этот URL:"
echo "curl https://<твое-имя>-11434.app.github.dev/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет!\"}]}'"
