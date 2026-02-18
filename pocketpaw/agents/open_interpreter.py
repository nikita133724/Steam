"""Open Interpreter agent wrapper.

Changes:
  2026-02-05 - Emit tool_use/tool_result events for Activity panel
  2026-02-04 - Filter out verbose console output, only show messages and final results
  2026-02-02 - Added executor layer logging for architecture visibility.
"""

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from pocketpaw.config import Settings

logger = logging.getLogger(__name__)


NON_ACTION_POLICY = (
    "Execution policy for this integration:\n"
    "- Do NOT run shell/code/tools for greetings or generic chat.\n"
    "- Only execute commands when user explicitly asks to run/test/install/change something.\n"
    "- If intent is unclear, ask a clarifying question first.\n"
    "- Do NOT invent pseudo-commands like update_skills() or refresh_skills_menu().\n"
    "- For skills management, prefer PocketPaw API endpoints (/api/skills, /api/skills/reload) instead of shell stubs.\n"
    "- Never continue with self-initiated multi-step actions after a plain informational reply; wait for user confirmation.\n"
    "- Never modify/delete/create server files or run privileged commands unless user gave explicit approval in this chat.\n"
    "- Never claim that a command/config change was done unless there is actual tool output confirming it.\n"
    "- Before using any filesystem path or endpoint, verify it exists/reachable; if not, ask user instead of guessing.\n"
)

EXPLICIT_ACTION_HINTS = (
    "run ", "execute ", "install ", "update ", "upgrade ", "delete ", "remove ",
    "create ", "edit ", "write ", "change ", "fix ", "restart ", "reload ",
    "запусти", "выполни", "установи", "обнови", "удали", "создай", "измени", "исправ",
    "перезапусти", "перезагрузи", "сделай", "примени", "проверь", "открой", "покажи"
)

QUESTION_HINTS = (
    "?", "как", "почему", "зачем", "что", "где", "когда", "можно", "подскажи", "расскажи"
)


def _is_explicit_action_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False

    # Questions should default to chat-only unless a direct imperative command is present.
    has_question = any(h in lowered for h in QUESTION_HINTS)

    # Strong imperative patterns (RU/EN) for actually executing actions.
    imperative_patterns = [
        r"(^|\s)(please\s+)?(run|execute|install|update|upgrade|restart|reload)\b",
        r"(^|\s)(запусти|выполни|установи|обнови|перезапусти|перезагрузи)\b",
        r"\b(выполни\s+команд|run\s+the\s+command|execute\s+this)\b",
    ]
    has_imperative = any(re.search(p, lowered) for p in imperative_patterns)

    # Extra fallback for obvious action wording.
    has_action_hint = any(h in lowered for h in EXPLICIT_ACTION_HINTS)

    if has_question and not has_imperative:
        return False

    return has_imperative or has_action_hint

SKILLS_RUNTIME_FACTS = (
    "PocketPaw skills runtime facts:\n"
    "- Built-in skill loader scans ONLY ~/.agents/skills and ~/.pocketpaw/skills.\n"
    "- Do NOT assume skills live in site-packages (e.g. .../site-packages/pocketpaw/skills).\n"
    "- To refresh skills in web mode, use PocketPaw API endpoint POST /api/skills/reload on the active dashboard host/port.\n"
    "- Never invent pseudo paths/commands like ~/.agents/pocketpaw/reload."
)


@dataclass(frozen=True)
class OpenInterpreterLLMConfig:
    """Resolved Open Interpreter LLM configuration."""

    provider: str
    model: str
    api_key: str | None
    api_base: str | None = None
    provider_id: str | None = None


def resolve_open_interpreter_llm(settings: Settings) -> OpenInterpreterLLMConfig:
    """Resolve provider/model specifically for Open Interpreter backend."""

    provider = settings.open_interpreter_provider or "auto"

    if provider == "auto":
        if settings.groq_api_key or getattr(settings, "groq_api_keys", ""):
            provider = "groq"
        elif settings.openai_api_key:
            provider = "openai"
        elif settings.anthropic_api_key:
            provider = "anthropic"
        else:
            provider = "ollama"

    if provider == "groq":
        groq_key = settings.groq_api_key
        if not groq_key and getattr(settings, "groq_api_keys", ""):
            groq_key = next(
                (k.strip() for k in settings.groq_api_keys.replace(",", "\n").splitlines() if k.strip()),
                None,
            )
        return OpenInterpreterLLMConfig(
            provider="groq",
            model=settings.open_interpreter_model or "llama-3.1-8b-instant",
            api_key=groq_key,
            api_base="https://api.groq.com/openai/v1",
        )

    if provider == "openai":
        return OpenInterpreterLLMConfig(
            provider="openai",
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            api_base="https://api.openai.com/v1",
        )

    if provider == "anthropic":
        return OpenInterpreterLLMConfig(
            provider="anthropic",
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )

    return OpenInterpreterLLMConfig(
        provider="ollama",
        model=settings.ollama_model,
        api_key=None,
        api_base=settings.ollama_host,
    )


class OpenInterpreterAgent:
    """Wraps Open Interpreter for autonomous task execution.

    In the Agent SDK architecture, this serves as the EXECUTOR layer:
    - Executes code and system commands
    - Handles file operations
    - Provides sandboxed execution environment
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._interpreter = None
        self._stop_flag = False
        self._semaphore = asyncio.Semaphore(1)
        self._groq_key_index = 0
        self._openai_key_index = 0
        self._provider_rr_index = 0
        self._provider_key_indices: dict[str, int] = {}
        self._active_provider_id: str | None = None
        self._request_times: deque[float] = deque()
        self._last_request_ts: float = 0.0
        self._active_executor_future: asyncio.Future | None = None
        self._initialize()

    def _load_custom_providers(self) -> list[dict]:
        raw = getattr(self.settings, "open_interpreter_provider_registry", "") or ""
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except Exception:
            logger.warning("⚠️ Invalid open_interpreter_provider_registry JSON")
        return []

    def _next_key_for_provider(self, provider_id: str, keys: list[str]) -> str | None:
        if not keys:
            return None
        idx = self._provider_key_indices.get(provider_id, 0)
        key = keys[idx % len(keys)]
        self._provider_key_indices[provider_id] = idx + 1
        return key

    def _detect_provider_from_endpoint(self, api_base: str | None) -> str:
        """Infer provider from endpoint; default to OpenAI-compatible protocol."""
        base = (api_base or "").lower()
        if not base:
            return "openai"

        # Ollama-compatible cloud endpoints may expose /api/generate or /api/chat.
        if "ollama.com" in base or "/api/generate" in base or "/api/chat" in base:
            return "ollama"

        # If endpoint already exposes OpenAI-style chat path, treat it as OpenAI-compatible,
        # even if hostname contains words like "ollama".
        if "/chat/completions" in base or "/openai" in base:
            return "openai"
        if "generativelanguage.googleapis.com" in base or "gemini" in base:
            return "gemini"
        if "anthropic.com" in base:
            return "anthropic"
        if "localhost:11434" in base or "127.0.0.1:11434" in base:
            return "ollama"
        return "openai"

    def _normalize_api_base_for_provider(self, provider: str, api_base: str | None) -> str | None:
        """Normalize provider endpoint to what Open Interpreter/LiteLLM expects."""
        if not api_base:
            return api_base

        normalized = api_base.strip().rstrip("/")
        if provider == "ollama":
            # OI/LiteLLM expects host base; keep path-less root to avoid
            # accidental OpenAI chat route concatenation with /api/generate.
            for suffix in ("/api/generate", "/api/chat", "/v1/chat/completions"):
                if normalized.endswith(suffix):
                    normalized = normalized[: -len(suffix)]
                    break
            if not normalized:
                normalized = api_base.strip().rstrip("/")

        return normalized

    def _normalize_model_for_provider(self, provider: str, model: str) -> str:
        model = (model or "").strip()
        if not model:
            return model
        if provider == "gemini" and not model.startswith("gemini/"):
            return f"gemini/{model}"
        if provider == "anthropic" and not model.startswith("anthropic/") and not model.startswith("claude"):
            return f"anthropic/{model}"
        return model

    def _resolve_custom_provider(self, provider_id: str) -> OpenInterpreterLLMConfig | None:
        for item in self._load_custom_providers():
            if item.get("id") != provider_id or item.get("enabled", True) is False:
                continue
            model = str(item.get("model", "")).strip()
            api_base = str(item.get("api_base", "")).strip() or None
            provider = str(item.get("provider", "")).strip().lower() or self._detect_provider_from_endpoint(api_base)

            keys_raw = item.get("api_keys", item.get("api_key", []))
            if isinstance(keys_raw, str):
                keys = [k.strip() for k in keys_raw.replace(",", "\n").splitlines() if k.strip()]
            elif isinstance(keys_raw, list):
                keys = [str(k).strip() for k in keys_raw if str(k).strip()]
            else:
                keys = []
            key = self._next_key_for_provider(provider_id, keys)
            if not model:
                return None
            return OpenInterpreterLLMConfig(
                provider=provider,
                model=self._normalize_model_for_provider(provider, model),
                api_key=key,
                api_base=self._normalize_api_base_for_provider(provider, api_base),
                provider_id=provider_id,
            )
        return None

    def _resolve_runtime_llm(self, *, on_error: bool = False) -> OpenInterpreterLLMConfig:
        selected = self.settings.open_interpreter_provider or "auto"
        mode = getattr(self.settings, "open_interpreter_registry_mode", "selected")

        if selected == "registry_auto":
            providers = [
                p.get("id")
                for p in self._load_custom_providers()
                if p.get("id") and p.get("enabled", True) is not False
            ]
            if providers:
                if mode in {"round_robin", "failover"}:
                    if on_error:
                        self._provider_rr_index += 1
                    provider_id = providers[self._provider_rr_index % len(providers)]
                    if not on_error:
                        self._provider_rr_index += 1
                else:
                    provider_id = providers[0]
                cfg = self._resolve_custom_provider(provider_id)
                if cfg:
                    return cfg

        custom = self._resolve_custom_provider(selected)
        if custom:
            return custom

        resolved = resolve_open_interpreter_llm(self.settings)
        if resolved.provider == "groq":
            return replace(resolved, api_key=self._next_groq_key() or resolved.api_key)
        if resolved.provider == "openai":
            return replace(resolved, api_key=self._next_openai_key() or resolved.api_key)
        return resolved

    def _has_runtime_fallback(self, llm: OpenInterpreterLLMConfig) -> bool:
        """Return True if failover can select a different key/provider."""

        selected = self.settings.open_interpreter_provider or "auto"
        mode = getattr(self.settings, "open_interpreter_registry_mode", "selected")

        if selected == "registry_auto" and mode in {"round_robin", "failover"}:
            active = [
                p
                for p in self._load_custom_providers()
                if p.get("id") and p.get("enabled", True) is not False
            ]
            if len(active) > 1:
                return True

        provider_id = llm.provider_id or ""
        if provider_id:
            custom = next(
                (
                    p
                    for p in self._load_custom_providers()
                    if p.get("id") == provider_id and p.get("enabled", True) is not False
                ),
                None,
            )
            if custom:
                keys_raw = custom.get("api_keys", custom.get("api_key", []))
                if isinstance(keys_raw, str):
                    keys = [k.strip() for k in keys_raw.replace(",", "\n").splitlines() if k.strip()]
                elif isinstance(keys_raw, list):
                    keys = [str(k).strip() for k in keys_raw if str(k).strip()]
                else:
                    keys = []
                return len(keys) > 1

        if llm.provider == "groq":
            return len(self._get_groq_keys()) > 1
        if llm.provider == "openai":
            return len(self._get_openai_keys()) > 1
        return False

    @staticmethod
    def _is_quota_like_error(error_text: str) -> bool:
        lowered = (error_text or "").lower()
        return any(
            token in lowered
            for token in (
                "quota",
                "insufficient_quota",
                "max budget",
                "billing",
                "credit",
            )
        )

    def _apply_llm_config(self, llm: OpenInterpreterLLMConfig) -> None:
        if llm.provider == "ollama":
            self._interpreter.llm.model = f"ollama/{llm.model}"
            self._interpreter.llm.api_base = llm.api_base
            # Keep explicit API keys for hosted Ollama-compatible endpoints
            # (e.g. ollama.com or private gateways). Local Ollama does not
            # require a key, so preserve previous behavior as fallback.
            self._interpreter.llm.api_key = llm.api_key or "ollama"
        else:
            self._interpreter.llm.model = llm.model
            self._interpreter.llm.api_base = llm.api_base
            self._interpreter.llm.api_key = llm.api_key

        configured_max_tokens = max(
            256,
            int(getattr(self.settings, "open_interpreter_max_tokens", 2090) or 2090),
        )
        self._interpreter.llm.max_tokens = configured_max_tokens
        # Prevent hidden provider-side retry bursts for quota-limited models.
        if hasattr(self._interpreter.llm, "max_retries"):
            self._interpreter.llm.max_retries = 0
        if hasattr(self._interpreter.llm, "num_retries"):
            self._interpreter.llm.num_retries = 0

        if llm.provider in {"groq", "openai"} or llm.provider_id:
            self._interpreter.llm.context_window = 131072
        self._active_provider_id = llm.provider_id or llm.provider

    def _get_openai_keys(self) -> list[str]:
        """Return ordered, de-duplicated OpenAI keys from single + pooled config."""
        keys: list[str] = []
        if self.settings.openai_api_key:
            keys.append(self.settings.openai_api_key.strip())
        if getattr(self.settings, "openai_api_keys", ""):
            raw = self.settings.openai_api_keys.replace(",", "\n")
            keys.extend([k.strip() for k in raw.splitlines() if k.strip()])

        seen: set[str] = set()
        uniq: list[str] = []
        for k in keys:
            if k and k not in seen:
                uniq.append(k)
                seen.add(k)
        return uniq

    def _next_openai_key(self) -> str | None:
        keys = self._get_openai_keys()
        if not keys:
            return None
        key = keys[self._openai_key_index % len(keys)]
        self._openai_key_index += 1
        return key

    def _get_groq_keys(self) -> list[str]:
        """Return ordered, de-duplicated Groq keys from single + pooled config."""
        keys: list[str] = []
        if self.settings.groq_api_key:
            keys.append(self.settings.groq_api_key.strip())
        if getattr(self.settings, "groq_api_keys", ""):
            raw = self.settings.groq_api_keys.replace(",", "\n")
            keys.extend([k.strip() for k in raw.splitlines() if k.strip()])

        seen: set[str] = set()
        uniq: list[str] = []
        for k in keys:
            if k and k not in seen:
                uniq.append(k)
                seen.add(k)
        return uniq

    def _next_groq_key(self) -> str | None:
        keys = self._get_groq_keys()
        if not keys:
            return None
        key = keys[self._groq_key_index % len(keys)]
        self._groq_key_index += 1
        return key

    def _enforce_requests_per_minute(self) -> None:
        """Block briefly when Open Interpreter request/minute limit is reached."""
        limit = max(0, int(getattr(self.settings, "open_interpreter_requests_per_minute", 0) or 0))
        configured_min_interval = max(
            0.0,
            float(getattr(self.settings, "open_interpreter_min_request_interval_seconds", 0.0) or 0.0),
        )
        derived_interval = (60.0 / limit) if limit > 0 else 0.0
        min_interval = max(configured_min_interval, derived_interval)

        now = time.monotonic()
        if min_interval > 0 and self._last_request_ts > 0:
            delta = now - self._last_request_ts
            if delta < min_interval:
                sleep_for = min_interval - delta
                logger.info(
                    "⏱ Open Interpreter pacing delay active (%.1fs between provider calls). Waiting %.1fs",
                    min_interval,
                    sleep_for,
                )
                time.sleep(sleep_for)
                now = time.monotonic()

        if limit <= 0:
            self._last_request_ts = now
            return

        window = 60.0
        while self._request_times and (now - self._request_times[0]) >= window:
            self._request_times.popleft()

        if len(self._request_times) >= limit:
            wait_for = window - (now - self._request_times[0])
            if wait_for > 0:
                logger.info(
                    "⏱ Open Interpreter rate limit reached (%s req/min). Waiting %.1fs",
                    limit,
                    wait_for,
                )
                time.sleep(wait_for)
                now = time.monotonic()
                while self._request_times and (now - self._request_times[0]) >= window:
                    self._request_times.popleft()

        now = time.monotonic()
        self._request_times.append(now)
        self._last_request_ts = now

    def _initialize(self) -> None:
        """Initialize the Open Interpreter instance."""
        try:
            from interpreter import interpreter

            # Configure interpreter
            interpreter.auto_run = True  # Avoid hidden terminal prompts; approval handled by policy/chat intent gate
            interpreter.loop = False  # Prevent unsolicited autonomous action chains
            interpreter.conversation_history = False  # Keep token usage stable in bot mode

            # Disable shell active-line echo injections (can break malformed shell blocks)
            os.environ["INTERPRETER_ACTIVE_LINE_DETECTION"] = "false"

            # Initial LLM config (can be reselected per request)
            self._interpreter = interpreter
            llm = self._resolve_runtime_llm()
            self._apply_llm_config(llm)
            logger.info(
                "🤖 Open Interpreter provider: %s (%s)",
                (llm.provider_id or llm.provider).title(),
                llm.model,
            )

            if llm.provider == "groq" and not llm.api_key:
                logger.warning("⚠️ Groq selected for Open Interpreter but no groq_api_key configured")

            # Safety settings
            interpreter.safe_mode = "off"  # Prevent non-chat terminal approval prompts

            self._base_system_message = interpreter.system_message
            logger.info("=" * 50)
            logger.info("🔧 EXECUTOR: Open Interpreter initialized")
            logger.info("   └─ Role: Code execution, file ops, system commands")
            logger.info("=" * 50)

        except ImportError:
            logger.error("❌ Open Interpreter not installed. Run: pip install open-interpreter")
            self._interpreter = None
        except Exception as e:
            logger.error(f"❌ Failed to initialize Open Interpreter: {e}")
            self._interpreter = None

    async def run(
        self,
        message: str,
        *,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        system_message: str | None = None,
    ) -> AsyncIterator[dict]:
        """Run a message through Open Interpreter with real-time streaming.

        Args:
            message: User message to process.
            system_prompt: Dynamic system prompt from AgentContextBuilder.
            history: Recent session history (prepended as summary to prompt).
            system_message: Legacy kwarg, superseded by system_prompt.
        """
        if not self._interpreter:
            yield {"type": "message", "content": "❌ Open Interpreter not available."}
            return

        # Semaphore(1) ensures only one OI session runs at a time
        async with self._semaphore:
            self._stop_flag = False

            # If a previous worker thread is still alive, try a soft reset first.
            if self._active_executor_future and not self._active_executor_future.done():
                try:
                    if self._interpreter:
                        self._interpreter.reset()
                    await asyncio.wait_for(asyncio.shield(self._active_executor_future), timeout=2.0)
                except Exception:
                    pass

                if self._active_executor_future and not self._active_executor_future.done():
                    yield {
                        "type": "error",
                        "content": (
                            "⚠️ Предыдущая задача Open Interpreter всё ещё выполняется и блокирует новый запуск. "
                            "Дождитесь завершения или перезапустите backend."
                        ),
                    }
                    return

            # Apply system prompt if provided (prefer system_prompt over legacy system_message).
            # Reset each run to avoid prompt growth across turns.
            self._interpreter.system_message = self._base_system_message

            # Resolve and rotate provider/key each request per registry policy
            llm_cfg = self._resolve_runtime_llm()
            self._apply_llm_config(llm_cfg)
            logger.info(
                "Open Interpreter runtime LLM: provider=%s model=%s api_base=%s",
                llm_cfg.provider_id or llm_cfg.provider,
                llm_cfg.model,
                llm_cfg.api_base or "default",
            )
            effective_system = system_prompt or system_message
            chat_only = not _is_explicit_action_request(message)
            mode_guard = (
                "Chat-only mode for this turn: provide explanation/questions only. "
                "Do not execute shell/code/tools until user explicitly asks and confirms."
                if chat_only
                else ""
            )
            if effective_system:
                self._interpreter.system_message = (
                    f"{effective_system}\n\n{NON_ACTION_POLICY}\n\n{SKILLS_RUNTIME_FACTS}\n\n{mode_guard}\n\n{self._base_system_message}"
                )
            else:
                self._interpreter.system_message = (
                    f"{NON_ACTION_POLICY}\n\n{SKILLS_RUNTIME_FACTS}\n\n{mode_guard}\n\n{self._base_system_message}"
                )


            # If history provided, prepend a compact conversation summary to the prompt
            if history:
                max_messages = max(1, int(self.settings.open_interpreter_history_messages))
                max_chars = max(40, int(self.settings.open_interpreter_history_chars))
                summary_lines = ["[Recent conversation context]"]
                for msg in history[-max_messages:]:
                    role = msg.get("role", "user").capitalize()
                    content = msg.get("content", "")
                    if len(content) > max_chars:
                        content = content[:max_chars] + "..."
                    summary_lines.append(f"{role}: {content}")
                summary_lines.append("[End of context]\n")
                message = "\n".join(summary_lines) + message

            # Use a queue to stream chunks from the sync thread to the async generator
            chunk_queue: asyncio.Queue = asyncio.Queue()
            
            def run_sync():
                """Run interpreter in a thread, push chunks to queue.

                Open Interpreter chunk types:
                - role: "assistant", type: "message" -> Text to show user
                - role: "assistant", type: "code" -> Code being written
                - role: "computer", type: "console", start: true -> Execution starting
                - role: "computer", type: "console", format: "output" -> Final output
                - role: "computer", type: "console", end: true -> Execution done
                """
                current_message = []
                current_code: list[str] = []
                current_language = None
                shown_running = False
                emitted_chunks = 0
                can_failover = self._has_runtime_fallback(llm_cfg)

                def _emit(chunk: dict) -> None:
                    nonlocal emitted_chunks
                    emitted_chunks += 1
                    asyncio.run_coroutine_threadsafe(chunk_queue.put(chunk), loop)

                def _flush_pending_code() -> None:
                    nonlocal current_code, current_language
                    if not current_code:
                        return
                    code_text = "".join(current_code).strip()
                    if code_text:
                        lang = (current_language or "").strip()
                        fence_lang = lang if lang else "text"
                        _emit(
                            {
                                "type": "message",
                                "content": f"```{fence_lang}\n{code_text}\n```",
                            }
                        )
                    current_code = []

                def _stream_once() -> None:
                    nonlocal current_message, current_code, current_language, shown_running
                    self._enforce_requests_per_minute()
                    for chunk in self._interpreter.chat(message, stream=True):
                        if self._stop_flag:
                            break

                        if isinstance(chunk, dict):
                            chunk_role = chunk.get("role", "")
                            chunk_type = chunk.get("type", "")
                            content = chunk.get("content", "")
                            chunk_format = chunk.get("format", "")
                            is_start = chunk.get("start", False)
                            is_end = chunk.get("end", False)

                            # Handle computer/console chunks - emit tool events for Activity
                            if chunk_role == "computer":
                                if chunk_type == "console":
                                    # Ensure commands/code planned by the model are visible in chat
                                    _flush_pending_code()
                                    if is_start and current_language and not shown_running:
                                        # Emit tool_use event for Activity panel
                                        lang_display = current_language.title()
                                        _emit(
                                            {
                                                "type": "tool_use",
                                                "content": f"Running {lang_display}...",
                                                "metadata": {
                                                    "name": f"run_{current_language}",
                                                    "input": {},
                                                },
                                            }
                                        )
                                        shown_running = True
                                    elif is_end:
                                        # Emit tool_result event for Activity panel
                                        lang_display = (
                                            current_language.title() if current_language else "Code"
                                        )
                                        _emit(
                                            {
                                                "type": "tool_result",
                                                "content": f"{lang_display} execution completed",
                                                "metadata": {
                                                    "name": f"run_{current_language or 'code'}"
                                                },
                                            }
                                        )
                                        # Reset for next code block
                                        shown_running = False
                                    # Skip verbose active_line, intermediate output
                                    continue

                                # Surface non-console computer prompts (e.g. confirmations)
                                if content:
                                    _emit({"type": "message", "content": str(content)})
                                continue

                            # Handle assistant chunks
                            if chunk_role == "assistant":
                                if chunk_type == "code":
                                    # Capture language and buffer code so command snippets are sent to chat.
                                    current_language = chunk_format or "code"
                                    # Flush any pending prose before code block
                                    if current_message:
                                        _emit(
                                            {
                                                "type": "message",
                                                "content": "".join(current_message),
                                            }
                                        )
                                        current_message = []
                                    if content:
                                        current_code.append(str(content))
                                elif chunk_type == "message" and content:
                                    # Flush pending code before next prose segment
                                    _flush_pending_code()
                                    # Stream message chunks
                                    _emit({"type": "message", "content": content})
                        elif isinstance(chunk, str) and chunk:
                            current_message.append(chunk)

                try:
                    _stream_once()

                    # Flush remaining buffered content
                    _flush_pending_code()
                    if current_message:
                        _emit({"type": "message", "content": "".join(current_message)})

                    if emitted_chunks == 0:
                        # Some providers fail in OI internals and only print quota text to terminal,
                        # yielding no stream chunks and no exception. Try one failover rotation,
                        # then emit a hard error so planner can classify it.
                        if can_failover:
                            try:
                                llm_retry = self._resolve_runtime_llm(on_error=True)
                                self._apply_llm_config(llm_retry)
                                _stream_once()
                            except Exception:
                                pass
                        else:
                            logger.warning(
                                "Open Interpreter returned zero chunks and no fallback key/provider is available"
                            )

                        if emitted_chunks == 0:
                            _emit(
                                {
                                    "type": "error",
                                    "content": (
                                        "Agent error: provider returned no stream output "
                                        "(possible quota/rate-limit/auth issue in Open Interpreter runtime)."
                                    ),
                                }
                            )
                except Exception as e:
                    err = str(e).lower()
                    quota_like = self._is_quota_like_error(err)
                    # Auto-failover: next key/provider for common quota/rate/auth issues
                    if any(
                        t in err
                        for t in [
                            "rate limit",
                            "too many requests",
                            "429",
                            "quota",
                            "api key",
                            "unauthorized",
                            "401",
                            "forbidden",
                            "authentication",
                        ]
                    ) and (can_failover or not quota_like):
                        try:
                            llm_retry = self._resolve_runtime_llm(on_error=True)
                            self._apply_llm_config(llm_retry)
                            _stream_once()
                            return
                        except Exception as e2:
                            e = e2
                    _emit({"type": "error", "content": f"Agent error: {str(e)}"})
                finally:
                    # Signal completion
                    asyncio.run_coroutine_threadsafe(chunk_queue.put(None), loop)

            executor_future = None
            try:
                loop = asyncio.get_event_loop()

                # Start the sync function in a thread
                executor_future = loop.run_in_executor(None, run_sync)
                self._active_executor_future = executor_future

                # Yield chunks as they arrive
                idle_timeouts = 0
                max_idle_timeouts = 10
                aborted_on_idle_timeout = False
                while True:
                    try:
                        chunk = await asyncio.wait_for(chunk_queue.get(), timeout=60.0)
                        if chunk is None:  # End signal
                            break
                        idle_timeouts = 0
                        yield chunk
                    except TimeoutError:
                        idle_timeouts += 1

                        # If the worker is already done and queue is empty, stop waiting.
                        if executor_future.done():
                            break

                        # Avoid endless heartbeat loops when OI gets stuck.
                        if idle_timeouts >= max_idle_timeouts:
                            self._stop_flag = True
                            aborted_on_idle_timeout = True
                            yield {
                                "type": "error",
                                "content": (
                                    "⚠️ Open Interpreter завис и не вернул ответ вовремя. "
                                    "Остановил текущий запуск. Проверьте модель/провайдер и повторите запрос."
                                ),
                            }
                            break

                        yield {"type": "message", "content": "⏳ Still processing..."}

                # Wait for executor to finish, but do not hang forever if it got stuck.
                if aborted_on_idle_timeout:
                    try:
                        await asyncio.wait_for(executor_future, timeout=3.0)
                    except TimeoutError:
                        logger.warning("Open Interpreter worker did not stop after timeout abort")
                else:
                    await executor_future

            except Exception as e:
                logger.error(f"Open Interpreter error: {e}")
                yield {"type": "error", "content": f"❌ Agent error: {str(e)}"}
            finally:
                if (
                    executor_future is not None
                    and executor_future.done()
                    and self._active_executor_future is executor_future
                ):
                    self._active_executor_future = None

    async def stop(self) -> None:
        """Stop the agent execution."""
        self._stop_flag = True
        if self._interpreter:
            try:
                self._interpreter.reset()
            except Exception:
                pass
