#!/bin/bash

# 1. Установка Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Обновление PATH, если нужно
export PATH="$HOME/.ollama/bin:$PATH"

# 3. Скачиваем модель (можно заменить на нужную)
ollama pull llama3.2:3b

# 4. Запускаем Ollama API
nohup ollama serve > ollama.log 2>&1 &

sleep 2
echo "Ollama API запущен на localhost:11434"

# 5. Запуск ngrok (нужно вставить свой токен)
ngrok config add-authtoken 39ld8AoprRvDifymsvZdx1zriMf_FmTGhHjfQPidQfVRoAjw

nohup ngrok http 11434 --host-header="localhost:11434" > ngrok.log 2>&1 &

sleep 2
echo "ngrok запущен"
echo "Публичный адрес смотри в ngrok.log"
