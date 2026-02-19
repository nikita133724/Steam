#!/bin/bash

PORT=11434
MODEL="llama3.2:3b"

echo "Отправляем запрос к Ollama на localhost:$PORT..."
echo ""

curl -X POST "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": \"Привет\"
      }
    ]
  }"

echo ""
echo ""
echo "Готово."
