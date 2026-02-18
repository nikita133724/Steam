# Deep Work Planner — orchestrates 4-phase project planning via LLM.
# Created: 2026-02-12
# Updated: 2026-02-12 — Added research_depth parameter (none/quick/standard/deep).
#   'none' skips research entirely (no LLM call), passing empty notes to PRD.
#
# PlannerAgent runs research, PRD generation, task breakdown, and team
# assembly through AgentRouter, producing a PlannerResult that can be
# materialized into Mission Control objects.

import asyncio
import ast
import json
import logging
import re
from collections import deque

from pocketpaw.deep_work.models import AgentSpec, PlannerResult, TaskSpec
from pocketpaw.deep_work.prompts import (
    PRD_PROMPT,
    RESEARCH_PROMPT,
    RESEARCH_PROMPT_DEEP,
    RESEARCH_PROMPT_QUICK,
    TASK_BREAKDOWN_PROMPT,
    TEAM_ASSEMBLY_PROMPT,
)
from pocketpaw.mission_control.manager import MissionControlManager
from pocketpaw.mission_control.models import AgentProfile

logger = logging.getLogger(__name__)

# Regex to strip markdown code fences (```json ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


class PlannerAgent:
    """Orchestrates multi-phase project planning through LLM calls.

    Phases:
      1. Research — gather domain knowledge
      2. PRD — generate a product requirements document
      3. Task breakdown — decompose into atomic tasks (JSON)
      4. Team assembly — recommend agents for the project (JSON)

    Each phase runs a formatted prompt through AgentRouter and collects
    the streamed text output.
    """

    def __init__(self, manager: MissionControlManager):
        self.manager = manager

    async def ensure_profile(self) -> AgentProfile:
        """Get or create the 'deep-work-planner' agent in Mission Control."""
        existing = await self.manager.get_agent_by_name("deep-work-planner")
        if existing:
            return existing
        return await self.manager.create_agent(
            name="deep-work-planner",
            role="Project Planner & Architect",
            description=(
                "Researches domains, generates PRDs, breaks projects "
                "into executable tasks, and recommends team composition"
            ),
            specialties=["planning", "research", "architecture", "task-decomposition"],
            backend="claude_agent_sdk",
        )

    @staticmethod
    def _fallback_tasks_from_context(project_description: str) -> list[TaskSpec]:
        """Return a minimal safe task set when model output is unparsable.

        Keeps Deep Work flow operational on weaker/free-tier models that fail
        to produce strict JSON even after retry.
        """
        summary = (project_description or "").strip()
        if len(summary) > 240:
            summary = summary[:237] + "..."

        return [
            TaskSpec(
                key="t1",
                title="Analyze current project files and constraints",
                description=(
                    "Inspect the provided workspace/files, summarize current state, "
                    "and produce a concrete implementation checklist. "
                    f"User request summary: {summary}"
                ),
                task_type="agent",
                priority="high",
                tags=["analysis", "planning"],
                estimated_minutes=45,
                required_specialties=["python"],
                blocked_by_keys=[],
            ),
            TaskSpec(
                key="t2",
                title="Implement approved changes and verify behavior",
                description=(
                    "Apply required code changes based on analysis, run validation "
                    "checks/tests, and report results with file-level notes."
                ),
                task_type="agent",
                priority="high",
                tags=["implementation", "testing"],
                estimated_minutes=90,
                required_specialties=["python", "testing"],
                blocked_by_keys=["t1"],
            ),
            TaskSpec(
                key="t3",
                title="Human review and approval",
                description=(
                    "Review proposed/implemented changes and approve next actions, "
                    "including any install/execute steps requiring explicit consent."
                ),
                task_type="human",
                priority="medium",
                tags=["review", "approval"],
                estimated_minutes=15,
                required_specialties=["user"],
                blocked_by_keys=["t2"],
            ),
        ]

    @staticmethod
    def _fallback_prd_from_context(project_description: str, research_notes: str) -> str:
        """Build a deterministic PRD fallback when provider output is empty."""

        summary = (project_description or "").strip()
        if len(summary) > 500:
            summary = summary[:497] + "..."

        research_excerpt = (research_notes or "").strip()
        if len(research_excerpt) > 1200:
            research_excerpt = research_excerpt[:1197] + "..."
        if not research_excerpt:
            research_excerpt = "Research phase returned empty output; proceed with conservative assumptions."

        return (
            "# Problem Statement\n"
            f"{summary or 'User requested implementation work requiring structured execution.'}\n\n"
            "# Scope\n"
            "- Analyze existing repository and constraints\n"
            "- Implement required code changes with minimal risk\n"
            "- Validate behavior with available automated checks\n\n"
            "# Requirements\n"
            "1. Produce a concrete implementation plan from current codebase\n"
            "2. Apply changes incrementally and keep commits reviewable\n"
            "3. Run relevant checks/tests and report outcomes\n"
            "4. Escalate uncertain operations for explicit user approval\n\n"
            "# Non-Goals\n"
            "- Unapproved destructive operations\n"
            "- Unnecessary dependency churn\n\n"
            "# Technical Constraints\n"
            "- Respect repository instructions and coding conventions\n"
            "- Keep behavior deterministic under provider limitations\n"
            "- Prefer robust fallback behavior over hard failure\n\n"
            "# Research Notes\n"
            f"{research_excerpt}\n"
        )

    @staticmethod
    def _fallback_team_from_tasks(tasks: list[TaskSpec]) -> list[AgentSpec]:
        """Create a practical fallback team when model doesn't return valid JSON.

        Keeps behavior deterministic but avoids always returning the same single
        `execution-generalist` profile for every project.
        """
        specialties: set[str] = set()
        for t in tasks:
            if t.task_type == "agent":
                specialties.update(s.lower().strip() for s in t.required_specialties if s and s.strip())

        if not specialties:
            specialties = {"python", "testing"}

        buckets: dict[str, dict] = {
            "engineering-core": {
                "role": "Execution Engineer",
                "description": "Implements core project requirements and integration work.",
                "specialties": [],
            },
            "frontend-ui": {
                "role": "Frontend Engineer",
                "description": "Builds UI/UX, templates, and client-side interactions.",
                "specialties": [],
            },
            "qa-validation": {
                "role": "QA & Validation Engineer",
                "description": "Runs tests, validates acceptance criteria, and reports gaps.",
                "specialties": [],
            },
            "infra-ops": {
                "role": "Infra & Ops Engineer",
                "description": "Handles runtime configuration, deployment, and operations tasks.",
                "specialties": [],
            },
        }

        def _bucket_for_specialty(specialty: str) -> str:
            s = specialty.lower()
            if any(k in s for k in ("front", "ui", "html", "css", "javascript", "js", "react", "vue")):
                return "frontend-ui"
            if any(k in s for k in ("test", "qa", "quality", "validation")):
                return "qa-validation"
            if any(k in s for k in ("devops", "infra", "deploy", "docker", "k8s", "ops", "ci", "cd")):
                return "infra-ops"
            return "engineering-core"

        for spec in sorted(specialties):
            buckets[_bucket_for_specialty(spec)]["specialties"].append(spec)

        result: list[AgentSpec] = []
        for name, payload in buckets.items():
            spec_list = payload["specialties"]
            if not spec_list:
                continue
            result.append(
                AgentSpec(
                    name=name,
                    role=payload["role"],
                    description=payload["description"],
                    specialties=spec_list,
                    backend="open_interpreter",
                )
            )

        if result:
            return result

        return [
            AgentSpec(
                name="execution-generalist",
                role="Execution Generalist",
                description=(
                    "Fallback agent used when planner cannot produce structured team JSON. "
                    "Executes assigned implementation and validation tasks."
                ),
                specialties=sorted(specialties),
                backend="open_interpreter",
            )
        ]

    @staticmethod
    def _is_placeholder_response(raw: str) -> bool:
        """Detect non-answer placeholder text from slow/stuck providers."""
        normalized_raw = PlannerAgent._unwrap_provider_stream_payload(raw)
        if not normalized_raw or not normalized_raw.strip():
            return True

        norm = " ".join(normalized_raw.lower().split())
        placeholders = (
            "⏳ still processing...",
            "still processing...",
            "`json` disabled or not supported.",
            "json disabled or not supported.",
        )
        if any(p in norm for p in placeholders):
            return True

        if norm.startswith("the previous output was"):
            return True

        return False

    @staticmethod
    def _diagnostic_sample(raw: str, max_chars: int = 1600) -> str:
        """Compact raw model output for project metadata diagnostics."""
        if not raw:
            return ""
        compact = raw.replace("\r", "").strip()
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars] + "..."

    @staticmethod
    def _unwrap_provider_stream_payload(raw: str) -> str:
        """Normalize provider stream envelopes to plain assistant text.

        Supports common chunk formats:
        - Ollama JSON/JSONL (`response`, `message.content`)
        - OpenAI-style streamed chunks (`choices[].delta.content`, `choices[].message.content`)
        - SSE lines with `data: { ... }`
        """
        if not raw:
            return ""

        stripped = raw.strip()
        if not stripped:
            return ""

        def _extract_text(payload) -> str:
            if not isinstance(payload, dict):
                return ""

            def _text_from_content_block(content) -> str:
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, str):
                            if item:
                                parts.append(item)
                            continue
                        if not isinstance(item, dict):
                            continue
                        # OpenAI/Responses-style content fragments
                        for key in ("text", "content"):
                            value = item.get(key)
                            if isinstance(value, str) and value:
                                parts.append(value)
                        nested_text = item.get("output_text")
                        if isinstance(nested_text, str) and nested_text:
                            parts.append(nested_text)
                    if parts:
                        return "".join(parts)
                return ""

            # Ollama-style
            response = payload.get("response")
            if isinstance(response, str) and response:
                return response

            # Responses-style shortcuts
            for key in ("output_text", "generated_text", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value

            message = payload.get("message")
            if isinstance(message, dict):
                content = _text_from_content_block(message.get("content"))
                if content:
                    return content

            # OpenAI-style
            choices = payload.get("choices")
            if isinstance(choices, list):
                parts: list[str] = []
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        content = _text_from_content_block(delta.get("content"))
                        if content:
                            parts.append(content)
                    msg = choice.get("message")
                    if isinstance(msg, dict):
                        content = _text_from_content_block(msg.get("content"))
                        if content:
                            parts.append(content)
                    text = choice.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
                if parts:
                    return "".join(parts)

            # Nested common wrappers
            for key in ("data", "result", "output"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    nested_text = _extract_text(nested)
                    if nested_text:
                        return nested_text
                if isinstance(nested, list):
                    nested_parts: list[str] = []
                    for item in nested:
                        if isinstance(item, dict):
                            t = _extract_text(item)
                            if t:
                                nested_parts.append(t)
                    if nested_parts:
                        return "".join(nested_parts)
                if isinstance(nested, str) and nested.strip():
                    return nested

            return ""

        # Single JSON object payload
        try:
            single = json.loads(stripped)
            if isinstance(single, dict):
                extracted = _extract_text(single)
                if extracted.strip():
                    return extracted
        except Exception:
            pass

        # Multi-line JSON envelopes / SSE lines
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return stripped

        response_parts: list[str] = []
        seen_structured_line = False

        for line in lines:
            candidate = line
            if candidate.startswith("data:"):
                candidate = candidate[5:].strip()
            if candidate in {"[DONE]", "DONE"}:
                continue

            if not (candidate.startswith("{") and candidate.endswith("}")):
                # Non-JSON line means this isn't a structured stream envelope.
                return stripped

            try:
                payload = json.loads(candidate)
            except Exception:
                return stripped
            if not isinstance(payload, dict):
                return stripped

            seen_structured_line = True
            extracted = _extract_text(payload)
            if extracted:
                response_parts.append(extracted)

        if seen_structured_line and response_parts:
            return "".join(response_parts)

        return stripped

    @staticmethod
    def _derive_tasks_from_text(raw: str, project_description: str) -> list[TaskSpec]:
        """Best-effort conversion when model ignores JSON and returns prose.

        Extracts numbered requirements/bullets and converts them into TaskSpec
        so planner doesn't collapse to static 3-task fallback for every project.
        """
        text = PlannerAgent._unwrap_provider_stream_payload(raw)
        if not text:
            return []

        requirement_lines: list[str] = []
        in_requirements = False
        for line in text.splitlines():
            cleaned = line.strip().lstrip("•").strip()
            if not cleaned:
                continue

            lowered = cleaned.lower().rstrip(":")
            if lowered in {"requirements", "## requirements"}:
                in_requirements = True
                continue
            if in_requirements and lowered.startswith(("non-goals", "## non-goals", "technical constraints", "## technical constraints")):
                in_requirements = False

            if re.match(r"^\d+[\.)]\s+", cleaned):
                requirement_lines.append(re.sub(r"^\d+[\.)]\s+", "", cleaned))
            elif in_requirements and cleaned.startswith(("-", "*")):
                requirement_lines.append(cleaned[1:].strip())

        if not requirement_lines:
            return []

        tasks: list[TaskSpec] = []
        for idx, req in enumerate(requirement_lines[:12], start=1):
            key = f"t{idx}"
            tasks.append(
                TaskSpec(
                    key=key,
                    title=f"Implement requirement {idx}",
                    description=(
                        f"Deliver requirement: {req}. "
                        "Include concrete acceptance checks in the final report."
                    ),
                    task_type="agent",
                    priority="high" if idx <= 3 else "medium",
                    tags=["requirement", "implementation"],
                    estimated_minutes=45,
                    required_specialties=["python"],
                    blocked_by_keys=[f"t{idx-1}"] if idx > 1 else [],
                )
            )

        review_key = f"t{len(tasks)+1}"
        summary = (project_description or "").strip()
        if len(summary) > 160:
            summary = summary[:157] + "..."
        tasks.append(
            TaskSpec(
                key=review_key,
                title="Human review and approval",
                description=(
                    "Review implemented requirements and confirm next actions. "
                    f"Project summary: {summary}"
                ),
                task_type="human",
                priority="medium",
                tags=["review", "approval"],
                estimated_minutes=15,
                required_specialties=["user"],
                blocked_by_keys=[tasks[-1].key],
            )
        )
        return tasks

    async def plan(
        self,
        project_description: str,
        project_id: str = "",
        research_depth: str = "standard",
    ) -> PlannerResult:
        """Run all 4 planning phases and return a structured PlannerResult.

        Args:
            project_description: Natural language project description.
            project_id: ID of the project being planned.
            research_depth: How thorough to research — "none" (skip entirely),
                "quick", "standard", or "deep". None skips the research
                LLM call entirely, passing empty notes to subsequent phases.

        Broadcasts SystemEvents for each phase so the frontend can show
        progress (e.g. spinner text).
        """
        # Use the selected global agent backend for planning as well.
        # This respects Open Interpreter provider registry / custom API models.
        from pocketpaw.agents.router import AgentRouter
        from pocketpaw.config import get_settings

        router = AgentRouter(get_settings())
        parse_diagnostics: dict[str, dict] = {}

        try:
            # Phase 1: Research (depth controls prompt and thoroughness)
            if research_depth == "none":
                # Skip research entirely — no LLM call
                research = ""
            else:
                self._broadcast_phase(project_id, "research")
                research_prompts = {
                    "quick": RESEARCH_PROMPT_QUICK,
                    "standard": RESEARCH_PROMPT,
                    "deep": RESEARCH_PROMPT_DEEP,
                }
                prompt_template = research_prompts.get(research_depth, RESEARCH_PROMPT)
                research = await self._run_phase_prompt_or_empty(
                    router=router,
                    phase="research",
                    prompt=prompt_template.format(project_description=project_description),
                    context="research phase",
                )

            # Phase 2: PRD
            self._broadcast_phase(project_id, "prd")
            prd = await self._run_phase_prompt_or_empty(
                router=router,
                phase="prd",
                prompt=PRD_PROMPT.format(
                    project_description=project_description,
                    research_notes=research,
                ),
                context="prd phase",
            )
            if not (prd or "").strip():
                logger.warning("Planner PRD phase returned empty output; using deterministic fallback PRD")
                prd = self._fallback_prd_from_context(project_description, research)

            # Phase 3: Task breakdown
            self._broadcast_phase(project_id, "tasks")
            tasks_prompt = TASK_BREAKDOWN_PROMPT.format(
                project_description=project_description,
                prd_content=prd,
                research_notes=research,
                parse_diagnostics=parse_diagnostics,
            )
            tasks_attempts: list[str] = []
            tasks_raw = await self._run_phase_prompt_or_empty(
                router=router,
                phase="tasks",
                prompt=tasks_prompt,
                context="tasks phase",
            )
            tasks_attempts.append(self._diagnostic_sample(tasks_raw))
            tasks = self._parse_tasks(tasks_raw)

            # Retry once if task breakdown failed to parse
            if not tasks or self._is_placeholder_response(tasks_raw):
                logger.info("Retrying task breakdown with explicit JSON instruction")
                tasks_raw = await self._run_phase_prompt_or_empty(
                    router=router,
                    phase="tasks",
                    prompt=(
                        "Your previous response was not valid JSON or was incomplete. "
                        "Return ONLY a JSON array of task objects, no markdown, "
                        "no explanation, no thinking preamble — just the raw JSON array.\n\n"
                        + tasks_prompt
                    ),
                    context="tasks retry",
                )
                tasks_attempts.append(self._diagnostic_sample(tasks_raw))
                tasks = self._parse_tasks(tasks_raw)

            if not tasks:
                derived_tasks = self._derive_tasks_from_text(tasks_raw, project_description)
                if derived_tasks:
                    logger.warning(
                        "Planner task JSON parse failed; derived %s tasks from prose response",
                        len(derived_tasks),
                    )
                    parse_diagnostics["task_breakdown"] = {
                        "fallback_used": False,
                        "derived_from_text": True,
                        "attempts": tasks_attempts,
                    }
                    tasks = derived_tasks

            if not tasks:
                logger.warning("Planner produced no parseable tasks; using fallback minimal task set")
                parse_diagnostics["task_breakdown"] = {
                    "fallback_used": True,
                    "attempts": tasks_attempts,
                }
                tasks = self._fallback_tasks_from_context(project_description)
            elif len(tasks_attempts) > 1:
                parse_diagnostics["task_breakdown"] = {
                    "fallback_used": False,
                    "attempts": tasks_attempts,
                }

            # Phase 4: Team assembly
            self._broadcast_phase(project_id, "team")
            tasks_json_str = json.dumps([t.to_dict() for t in tasks], indent=2)
            team_prompt = TEAM_ASSEMBLY_PROMPT.format(tasks_json=tasks_json_str)
            team_attempts: list[str] = []
            team_raw = await self._run_phase_prompt_or_empty(
                router=router,
                phase="team",
                prompt=team_prompt,
                context="team phase",
            )
            team_attempts.append(self._diagnostic_sample(team_raw))
            team = self._parse_team(team_raw)

            # Retry once if team assembly failed to parse
            if not team or self._is_placeholder_response(team_raw):
                logger.info("Retrying team assembly with explicit JSON instruction")
                team_raw = await self._run_phase_prompt_or_empty(
                    router=router,
                    phase="team",
                    prompt=(
                        "Your previous response was not valid JSON or was incomplete. "
                        "Return ONLY a JSON array of agent objects, no markdown, "
                        "no explanation, no thinking preamble — just the raw JSON array.\n\n"
                        + team_prompt
                    ),
                    context="team retry",
                )
                team_attempts.append(self._diagnostic_sample(team_raw))
                team = self._parse_team(team_raw)

            if not team:
                logger.warning("Planner produced no parseable team; using fallback minimal team")
                parse_diagnostics["team_assembly"] = {
                    "fallback_used": True,
                    "attempts": team_attempts,
                }
                team = self._fallback_team_from_tasks(tasks)
            elif len(team_attempts) > 1:
                parse_diagnostics["team_assembly"] = {
                    "fallback_used": False,
                    "attempts": team_attempts,
                }

            # Split human tasks out for the result
            human_tasks = [t for t in tasks if t.task_type == "human"]
            agent_tasks = [t for t in tasks if t.task_type != "human"]

            # Build dependency graph: key -> [keys it depends on]
            dep_graph: dict[str, list[str]] = {}
            for t in tasks:
                if t.blocked_by_keys:
                    dep_graph[t.key] = list(t.blocked_by_keys)

            total_minutes = sum(t.estimated_minutes for t in tasks)

            return PlannerResult(
                project_id=project_id,
                prd_content=prd,
                tasks=agent_tasks,
                team_recommendation=team,
                human_tasks=human_tasks,
                dependency_graph=dep_graph,
                estimated_total_minutes=total_minutes,
                research_notes=research,
                parse_diagnostics=parse_diagnostics,
            )
        finally:
            try:
                await router.stop()
            except Exception:
                pass

    async def _run_prompt(self, prompt: str, router=None, *, phase: str = "unknown") -> str:
        """Run a planner prompt through selected backend and collect text only."""
        if router is None:
            from pocketpaw.agents.router import AgentRouter
            from pocketpaw.config import get_settings

            router = AgentRouter(get_settings())

        planner_system_prompt = (
            "You are a planning assistant. Return plain text or JSON only. "
            "Do NOT run tools, shell, code, or any external actions. "
            "At planning stage, do NOT install dependencies or suggest immediate execution. "
            "Any installation/execution steps must be marked as requiring explicit user approval first. "
            "Do NOT ask for confirmation; just provide the requested planning output."
        )

        output_parts: list[str] = []
        expect_json = "json" in (prompt or "").lower()
        stream = router.run(prompt, system_prompt=planner_system_prompt)
        stream_iter = stream.__aiter__()

        backend_name = getattr(getattr(router, "settings", None), "agent_backend", "")
        if backend_name == "open_interpreter":
            # OI backend may emit chunks with longer gaps while tool/runtime thread is busy.
            overall_timeout_s = 900.0
            chunk_idle_timeout_s = 180.0
        else:
            overall_timeout_s = 300.0
            chunk_idle_timeout_s = 60.0
        started = asyncio.get_event_loop().time()
        max_output_chars = 120000
        recent_norm_chunks: deque[str] = deque(maxlen=12)
        chunk_count = 0
        accepted_parts = 0

        logger.info(
            "Planner phase '%s' started (backend=%s, expect_json=%s)",
            phase,
            backend_name or "unknown",
            expect_json,
        )

        while True:
            elapsed = asyncio.get_event_loop().time() - started
            if elapsed >= overall_timeout_s:
                try:
                    await router.stop()
                except Exception:
                    pass
                raise TimeoutError(f"Planner phase reached overall timeout ({overall_timeout_s:.0f}s)")

            timeout = min(chunk_idle_timeout_s, max(0.1, overall_timeout_s - elapsed))
            try:
                chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                try:
                    await router.stop()
                except Exception:
                    pass

                # On slower/free-tier models, text phases can pause for long periods.
                # If we already have meaningful non-JSON output, continue with partial text
                # instead of failing the entire planning pipeline.
                if not expect_json and output_parts:
                    logger.warning(
                        "Planner phase stalled for %ss; using partial text output (%s chars)",
                        int(chunk_idle_timeout_s),
                        sum(len(part) for part in output_parts),
                    )
                    break

                raise TimeoutError(
                    f"Planner phase stalled for {chunk_idle_timeout_s:.0f}s without new output"
                ) from exc

            chunk_count += 1
            chunk_type = chunk.get("type")
            if chunk_type == "done":
                break
            if chunk_type == "error":
                raw_error = (chunk.get("content") or "Unknown backend error").strip()
                lowered = raw_error.lower()
                side = "backend"
                hint = ""
                if any(tok in lowered for tok in ("401", "unauthorized", "api key", "forbidden", "authentication")):
                    side = "llm_provider_auth"
                    hint = (
                        "Likely provider-side auth/config issue: verify endpoint + API key for the selected provider."
                    )
                elif any(tok in lowered for tok in ("quota", "insufficient_quota", "billing", "max budget")):
                    side = "llm_provider_quota"
                    hint = "Likely provider quota/budget issue: check billing/limits for the selected provider/key."
                elif any(tok in lowered for tok in ("timeout", "connection", "dns", "ssl", "temporarily unavailable")):
                    side = "network_or_provider_availability"
                    hint = "Likely network/provider availability issue."

                compact_error = " ".join(raw_error.split())
                if len(compact_error) > 420:
                    compact_error = compact_error[:420] + "..."
                raise RuntimeError(
                    f"Planner phase '{phase}' failed (backend={backend_name or 'unknown'}, side={side}): {compact_error}"
                    + (f" Hint: {hint}" if hint else "")
                )
            if chunk_type != "message":
                continue

            content = chunk.get("content", "")
            if not content:
                continue

            normalized_content = " ".join(content.lower().split())
            if expect_json and normalized_content in {"⏳ still processing...", "still processing..."}:
                # Heartbeat from Open Interpreter should not pollute JSON output.
                continue

            output_parts.append(content)
            accepted_parts += 1

            # If this phase expects JSON, return as soon as we captured
            # one complete valid JSON array to avoid post-JSON chatter.
            if expect_json:
                joined = "".join(output_parts)
                parsed_list = self._extract_first_json_array(joined)
                if parsed_list is not None:
                    return json.dumps(parsed_list, ensure_ascii=False)

            total_len = sum(len(part) for part in output_parts)
            if total_len >= max_output_chars:
                try:
                    await router.stop()
                except Exception:
                    pass
                logger.warning(
                    "Planner stream truncated at %s chars to prevent runaway generation",
                    max_output_chars,
                )
                break

            normalized = " ".join(content.lower().split())
            if normalized:
                recent_norm_chunks.append(normalized)
                if len(recent_norm_chunks) >= 8 and len(set(recent_norm_chunks)) <= 2:
                    try:
                        await router.stop()
                    except Exception:
                        pass
                    logger.warning("Planner stream stopped due to repetitive output loop detection")
                    break

        final_output = "".join(output_parts)
        logger.info(
            "Planner phase '%s' stream finished: chunks=%s accepted_parts=%s output_chars=%s",
            phase,
            chunk_count,
            accepted_parts,
            len(final_output),
        )

        return final_output

    async def _run_phase_prompt_or_empty(
        self,
        *,
        router,
        phase: str,
        prompt: str,
        context: str,
    ) -> str:
        """Run a planner phase prompt and degrade to empty text on backend failures."""

        try:
            return await self._run_prompt(prompt, router=router, phase=phase)
        except Exception as exc:
            compact_error = " ".join(str(exc).split())
            if len(compact_error) > 500:
                compact_error = compact_error[:500] + "..."
            logger.warning(
                "Planner %s failed; continuing with fallback path. error=%s",
                context,
                compact_error,
            )
            return ""

    def _parse_tasks(self, raw: str) -> list[TaskSpec]:
        """Parse LLM JSON output into a list of TaskSpec objects.

        Handles markdown code fences (```json ... ```) and returns an
        empty list on parse failure.
        """
        data = self._parse_json_list(raw, "task breakdown")
        if data is None:
            return []

        parsed: list[TaskSpec] = []
        for item in self._coerce_dict_list(data):
            try:
                parsed.append(TaskSpec.from_dict(item))
            except Exception as exc:
                logger.debug("Skipping invalid task item: %s", exc)
        return parsed

    def _parse_team(self, raw: str) -> list[AgentSpec]:
        """Parse LLM JSON output into a list of AgentSpec objects.

        Handles markdown code fences and returns an empty list on failure.
        """
        data = self._parse_json_list(raw, "team assembly")
        if data is None:
            return []

        parsed: list[AgentSpec] = []
        for item in self._coerce_dict_list(data):
            try:
                parsed.append(AgentSpec.from_dict(item))
            except Exception as exc:
                logger.debug("Skipping invalid team item: %s", exc)
        return parsed

    @staticmethod
    def _coerce_dict_item(item):
        """Best-effort conversion of JSON-ish item into dict."""
        if isinstance(item, dict):
            return item
        if isinstance(item, str):
            parsed = PlannerAgent._try_parse_json_like(item)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0]
        return None

    @staticmethod
    def _coerce_dict_list(data) -> list[dict]:
        """Normalize heterogeneous list payloads into list[dict]."""
        result: list[dict] = []
        if not isinstance(data, list):
            return result

        for item in data:
            normalized = PlannerAgent._coerce_dict_item(item)
            if normalized is not None:
                result.append(normalized)
        return result

    def _parse_json_list(self, raw: str, label: str) -> list[dict] | None:
        """Parse raw LLM output as a JSON list, with tolerant recovery.

        Returns None if parsing fails after best-effort recovery.
        """
        normalized_raw = self._unwrap_provider_stream_payload(raw)
        if not (normalized_raw or "").strip() and (raw or "").strip():
            normalized_raw = raw
        cleaned = self._strip_code_fences(normalized_raw)

        if not cleaned:
            logger.warning(
                "Failed to parse %s JSON: model returned empty output after stream normalization "
                "(raw_chars=%s, normalized_chars=%s). raw_sample=\n%s",
                label,
                len(raw or ""),
                len(normalized_raw or ""),
                (raw or "")[:600],
            )
            return None

        # 1) Strict JSON parse first
        strict_error: Exception | None = None
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                extracted_obj = self._extract_list_from_json_object(cleaned, label)
                if extracted_obj is not None:
                    return extracted_obj
            logger.warning("%s JSON is not a list (top-level type=%s)", label, type(data).__name__)
            return None
        except (json.JSONDecodeError, TypeError) as exc:
            strict_error = exc

        # 2) Noisy prose around JSON array
        extracted = self._extract_first_json_array(cleaned)
        if extracted is not None:
            return extracted

        # 3) Object-wrapped provider payloads (including nested content strings)
        extracted_obj = self._extract_list_from_json_object(normalized_raw, label)
        if extracted_obj is not None:
            return extracted_obj

        # 4) Relaxed Python-style literals (single quotes / True / None)
        relaxed = self._try_literal_eval_list(cleaned, label)
        if relaxed is not None:
            return relaxed

        logger.warning(
            "Failed to parse %s JSON (strict_error=%s). normalized_sample=\n%s\ncleaned_sample=\n%s",
            label,
            str(strict_error)[:180] if strict_error else "n/a",
            normalized_raw[:400],
            cleaned[:400],
        )
        return None

    @staticmethod
    def _extract_list_from_json_object(raw: str, label: str) -> list[dict] | None:
        """Extract list-like payloads from object-wrapped model responses.

        Handles both direct object forms like {"tasks": [...]} and nested
        wrapper payloads where JSON is embedded as string fields.
        """
        if not raw:
            return None

        cleaned = PlannerAgent._strip_code_fences(raw)
        root = PlannerAgent._try_parse_json_like(cleaned)
        if not isinstance(root, dict):
            obj = PlannerAgent._extract_first_json_object(cleaned)
            if isinstance(obj, dict):
                root = obj
            else:
                return None

        candidate_keys = {
            "task breakdown": ["tasks", "task_breakdown", "taskBreakdown", "work_items", "items", "data", "result"],
            "team assembly": ["team", "agents", "team_recommendation", "team_recommendations", "crew", "items", "data", "result"],
        }.get(label, ["items", "data", "result"])

        def _walk(node, depth: int = 0):
            if depth > 5:
                return None
            if isinstance(node, list):
                if node and all(isinstance(x, dict) for x in node):
                    return node
                return None
            if isinstance(node, dict):
                for key in candidate_keys:
                    value = node.get(key)
                    if isinstance(value, list):
                        return value
                    if isinstance(value, str):
                        parsed = PlannerAgent._try_parse_json_like(value)
                        found = _walk(parsed, depth + 1)
                        if found is not None:
                            return found

                for value in node.values():
                    if isinstance(value, str):
                        parsed = PlannerAgent._try_parse_json_like(value)
                        found = _walk(parsed, depth + 1)
                        if found is not None:
                            return found
                    elif isinstance(value, (dict, list)):
                        found = _walk(value, depth + 1)
                        if found is not None:
                            return found
            return None

        return _walk(root)

    @staticmethod
    def _try_parse_json_like(text: str):
        """Best-effort parse for JSON-ish string payloads."""
        if not isinstance(text, str):
            return None

        candidate = PlannerAgent._strip_code_fences(text)
        if not candidate:
            return None

        try:
            return json.loads(candidate)
        except Exception:
            pass

        arr = PlannerAgent._extract_first_json_array(candidate)
        if arr is not None:
            return arr

        obj = PlannerAgent._extract_first_json_object(candidate)
        if obj is not None:
            return obj

        return None

    @staticmethod
    def _try_literal_eval_list(text: str, label: str) -> list[dict] | None:
        """Parse Python-style list/dict literals as a fallback."""
        try:
            value = ast.literal_eval(text)
        except Exception:
            return None

        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            extracted = PlannerAgent._extract_list_from_json_object(str(value), label)
            if extracted is not None:
                return extracted
        return None

    @staticmethod
    def _extract_first_json_array(text: str) -> list[dict] | None:
        """Extract and parse the first JSON array from noisy LLM output."""
        if not text:
            return None

        start = text.find("[")
        while start != -1:
            depth = 0
            in_string = False
            escaped = False

            for idx in range(start, len(text)):
                ch = text[idx]

                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : idx + 1]
                        try:
                            parsed = json.loads(candidate)
                        except Exception:
                            break
                        if isinstance(parsed, list):
                            return parsed
                        break

            start = text.find("[", start + 1)

        return None

    @staticmethod
    def _extract_first_json_object(text: str) -> dict | None:
        """Extract and parse the first JSON object from noisy LLM output."""
        if not text:
            return None

        start = text.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escaped = False

            for idx in range(start, len(text)):
                ch = text[idx]

                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : idx + 1]
                        try:
                            parsed = json.loads(candidate)
                        except Exception:
                            break
                        if isinstance(parsed, dict):
                            return parsed
                        break

            start = text.find("{", start + 1)

        return None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences from LLM output.

        Extracts content from ```json ... ``` or ``` ... ``` blocks.
        If no fences found, returns the original text stripped.
        """
        match = _CODE_FENCE_RE.search(text)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _broadcast_phase(self, project_id: str, phase: str) -> None:
        """Publish a SystemEvent for frontend progress tracking.

        This is best-effort — if the bus is not running (e.g. in tests),
        the error is silently ignored.
        """
        phase_messages = {
            "research": "Researching domain knowledge...",
            "prd": "Writing product requirements...",
            "tasks": "Breaking down into tasks...",
            "team": "Assembling agent team...",
        }
        message = phase_messages.get(phase, f"Planning phase: {phase}")

        try:
            from pocketpaw.bus import get_message_bus
            from pocketpaw.bus.events import SystemEvent

            bus = get_message_bus()
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    bus.publish_system(
                        SystemEvent(
                            event_type="dw_planning_phase",
                            data={
                                "project_id": project_id,
                                "phase": phase,
                                "message": message,
                            },
                        )
                    )
                )
            except RuntimeError:
                pass  # No event loop running
        except Exception:
            pass  # Bus may not be available in tests
