# Deep Work Planner — orchestrates 4-phase project planning via LLM.
# Created: 2026-02-12
# Updated: 2026-02-12 — Added research_depth parameter (none/quick/standard/deep).
#   'none' skips research entirely (no LLM call), passing empty notes to PRD.
#
# PlannerAgent runs research, PRD generation, task breakdown, and team
# assembly through AgentRouter, producing a PlannerResult that can be
# materialized into Mission Control objects.

import asyncio
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
    def _fallback_team_from_tasks(tasks: list[TaskSpec]) -> list[AgentSpec]:
        """Create a minimal team recommendation when model doesn't return one."""
        specialties: set[str] = set()
        for t in tasks:
            if t.task_type == "agent":
                specialties.update(t.required_specialties)

        # Keep a compact but useful default team.
        if not specialties:
            specialties = {"python", "testing"}

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
                research = await self._run_prompt(
                    prompt_template.format(project_description=project_description),
                    router=router,
                )

            # Phase 2: PRD
            self._broadcast_phase(project_id, "prd")
            prd = await self._run_prompt(
                PRD_PROMPT.format(
                    project_description=project_description,
                    research_notes=research,
                ),
                router=router,
            )

            # Phase 3: Task breakdown
            self._broadcast_phase(project_id, "tasks")
            tasks_raw = await self._run_prompt(
                TASK_BREAKDOWN_PROMPT.format(
                    project_description=project_description,
                    prd_content=prd,
                    research_notes=research,
                ),
                router=router,
            )
            tasks = self._parse_tasks(tasks_raw)

            # Retry once if task breakdown failed to parse
            if not tasks:
                logger.info("Retrying task breakdown with explicit JSON instruction")
                tasks_raw = await self._run_prompt(
                    "Your previous response was not valid JSON. "
                    "Return ONLY a JSON array of task objects, no markdown, "
                    "no explanation — just the raw JSON array.\n\n"
                    + TASK_BREAKDOWN_PROMPT.format(
                        project_description=project_description,
                        prd_content=prd,
                        research_notes=research,
                    ),
                    router=router,
                )
                tasks = self._parse_tasks(tasks_raw)

            if not tasks:
                logger.warning("Planner produced no parseable tasks; using fallback minimal task set")
                tasks = self._fallback_tasks_from_context(project_description)

            # Phase 4: Team assembly
            self._broadcast_phase(project_id, "team")
            tasks_json_str = json.dumps([t.to_dict() for t in tasks], indent=2)
            team_raw = await self._run_prompt(
                TEAM_ASSEMBLY_PROMPT.format(tasks_json=tasks_json_str),
                router=router,
            )
            team = self._parse_team(team_raw)

            if not team:
                logger.warning("Planner produced no parseable team; using fallback minimal team")
                team = self._fallback_team_from_tasks(tasks)

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
            )
        finally:
            try:
                await router.stop()
            except Exception:
                pass

    async def _run_prompt(self, prompt: str, router=None) -> str:
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

            chunk_type = chunk.get("type")
            if chunk_type == "done":
                break
            if chunk_type != "message":
                continue

            content = chunk.get("content", "")
            if not content:
                continue

            output_parts.append(content)

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

        return "".join(output_parts)


    def _parse_tasks(self, raw: str) -> list[TaskSpec]:
        """Parse LLM JSON output into a list of TaskSpec objects.

        Handles markdown code fences (```json ... ```) and returns an
        empty list on parse failure.
        """
        data = self._parse_json_list(raw, "task breakdown")
        if data is None:
            return []
        return [TaskSpec.from_dict(item) for item in data if isinstance(item, dict)]

    def _parse_team(self, raw: str) -> list[AgentSpec]:
        """Parse LLM JSON output into a list of AgentSpec objects.

        Handles markdown code fences and returns an empty list on failure.
        """
        data = self._parse_json_list(raw, "team assembly")
        if data is None:
            return []
        return [AgentSpec.from_dict(item) for item in data if isinstance(item, dict)]

    def _parse_json_list(self, raw: str, label: str) -> list[dict] | None:
        """Parse raw LLM output as a JSON list, with one retry on failure.

        Returns None if parsing fails after retry.
        """
        cleaned = self._strip_code_fences(raw)
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
            logger.warning(f"{label} JSON is not a list")
            return None
        except (json.JSONDecodeError, TypeError):
            # Some models prepend/append prose even when asked for raw JSON.
            # Try best-effort extraction of the first valid JSON array.
            extracted = self._extract_first_json_array(cleaned)
            if extracted is not None:
                return extracted

            logger.warning("Failed to parse %s JSON (will retry):\n%s", label, raw[:200])
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
