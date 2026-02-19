#!/bin/bash
set -e

MODEL="llama3.2:3b"
PORT=11434
OLLAMA_PATH="$HOME/.ollama/bin"

export PATH="$OLLAMA_PATH:$PATH"

# 1) Проверка Ollama
if ! command -v ollama &> /dev/null; then
    echo "Ollama не найден — устанавливаем..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama уже установлен"
fi

# 2) Проверяем модель
echo "Проверяем модель $MODEL..."
ollama list | grep "$MODEL" || ollama pull $MODEL

# 3) Убиваем старый сервер если есть
pkill -f "ollama serve" || true

# 4) ВАЖНО: слушаем 0.0.0.0
export OLLAMA_HOST=0.0.0.0

echo "Запускаем Ollama API..."
nohup ollama serve > ollama.log 2>&1 &

sleep 5

echo "Проверяем локально..."
curl http://127.0.0.1:$PORT/v1/models

echo ""
echo "Готово."
echo "Теперь зайди в:"
echo "Ports → 11434 → Visibility → Public"
echo ""
echo "Твой публичный URL будет вида:"
echo "https://<твое-имя>-11434.app.github.dev"
echo ""
echo "Пример запроса:"
echo "curl https://<твое-имя>-11434.app.github.dev/v1/chat/completions \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Привет!\"}]}'"
