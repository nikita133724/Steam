# Open Interpreter + Groq (PocketPaw 0.4.0)

## Что добавлено
- Провайдер **Groq** для backend `open_interpreter`.
- Отдельные настройки Open Interpreter:
  - `open_interpreter_provider`
  - `open_interpreter_model` (по умолчанию: `llama-3.1-8b-instant`)
- Поддержка сохранения ключа `groq_api_key` через UI (API Keys).
- Поддержка пула ключей `groq_api_keys` (несколько ключей, по одному на строку).
- Универсальный реестр провайдеров `open_interpreter_provider_registry` (JSON):
  можно добавить любые OpenAI-compatible провайдеры со своими endpoint/model/key-pool.
- Политики маршрутизации `open_interpreter_registry_mode`:
  - `selected` — только выбранный провайдер,
  - `round_robin` — циклическое переключение провайдеров/ключей,
  - `failover` — переключение при ошибках rate-limit/quota/auth.
- Для Groq используется OpenAI-compatible endpoint:
  - `https://api.groq.com/openai/v1/chat/completions`

## Как включить в WebUI
1. Откройте **Settings → API Keys**.
2. Вставьте ключ в поле **Groq API Key (Open Interpreter)** и нажмите **Save**.
3. Перейдите в **Settings → General**.
4. Установите:
   - **Agent Backend** = `Open Interpreter`
   - **Open Interpreter Provider** = `Groq`
5. При необходимости поменяйте **Open Interpreter Model (Groq)**.
   - Значение по умолчанию: `llama-3.1-8b-instant`.
6. Для multi-provider сценариев заполните **Open Interpreter Provider Registry (JSON)**
   и выберите `registry_auto` в **Open Interpreter Provider**.

## Где хранится ключ
- Ключ `groq_api_key` сохраняется в encrypted credential store (`~/.pocketpaw/secrets.enc`),
  как и остальные секреты.
- Пул ключей `groq_api_keys` хранится там же и используется для ротации.

## Важно про маршрутизацию запросов
- Когда выбран backend `open_interpreter`, ответы идут через `OpenInterpreterAgent`.
- Когда в нём выбран provider `groq`, LLM вызовы идут через Groq endpoint.
- Cloud-ветка PocketPaw (`claude_agent_sdk` / обычный router) в этом режиме не используется.

## Снижение расхода токенов
Добавлены настройки контекста Open Interpreter:
- `open_interpreter_history_messages` (по умолчанию 4)
- `open_interpreter_history_chars` (по умолчанию 120)

Также исправлен важный баг: system prompt больше не накапливается от сообщения к сообщению,
что раньше могло сильно раздувать токены.

Дополнительно:
- Для shell-исполнения отключён active-line echo injection в интеграции PocketPaw,
  чтобы избежать ошибок вида `syntax error near unexpected token 'echo'` на некорректных
  или пустых shell-блоках.


## Custom Registry без поля provider
Можно указывать только:
- `id`
- `api_base`
- `model`
- `api_keys` (или `api_key`)
- `enabled`

Поле `provider` теперь необязательно: интеграция пытается авто-определить протокол по endpoint.

Пример:
```json
[
  {
    "id": "grok-a",
    "api_base": "https://api.groq.com/openai/v1",
    "model": "llama-3.1-8b-instant",
    "api_keys": ["gsk_1", "gsk_2"],
    "enabled": true
  },
  {
    "id": "gemini-a",
    "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
    "model": "gemini-1.5-pro",
    "api_key": "AIza...",
    "enabled": true
  }
]
```

> Важно: если endpoint OpenAI-compatible, все различия JSON-схемы скрываются LiteLLM/OpenInterpreter.
> Для нативных endpoint, не совместимых с OpenAI-форматом, может потребоваться отдельный provider-adapter.


## Лимит запросов в минуту (Open Interpreter)
- Параметр: `open_interpreter_requests_per_minute`
- `0` = без лимита.
- `N > 0`: если модель/агент пытается сделать больше `N` LLM-запросов за минуту, интеграция подождёт до освобождения окна и продолжит.

Это полезно для провайдеров с жёсткими RPM-ограничениями (например GPT 3 RPM).
