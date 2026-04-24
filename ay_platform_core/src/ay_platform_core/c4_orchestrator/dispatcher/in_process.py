# =============================================================================
# File: in_process.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/dispatcher/in_process.py
# Description: In-process agent dispatcher. Invokes the C8 LLM gateway
#              client with the agent-appropriate headers, interprets the
#              response as an AgentCompletion envelope, and returns it.
#              Replaces the real Kubernetes pod dispatcher until infra is
#              ready (R-200-030 / Q-200-001 baseline).
#
# @relation implements:R-200-021
# @relation implements:R-200-030
# =============================================================================

from __future__ import annotations

import json
import time
from typing import Any

from ay_platform_core.c4_orchestrator.dispatcher.base import (
    DispatchRequest,
)
from ay_platform_core.c4_orchestrator.models import (
    AgentBlocker,
    AgentCompletion,
    AgentConcern,
    AgentNeedsContext,
    AgentRole,
    EscalationStatus,
    Phase,
)
from ay_platform_core.c8_llm.client import LLMGatewayClient
from ay_platform_core.c8_llm.models import (
    ChatCompletionRequest,
    ChatMessage,
    ChatRole,
)

# Per-phase system prompts. Intentionally minimal — v1 uses generic
# prompts per D-011 caveat. Production-grade prompt libraries live in
# operational config, not in code.
_SYSTEM_PROMPTS: dict[Phase, str] = {
    Phase.BRAINSTORM: (
        "You are the Architect agent. Elicit intent and produce an initial "
        "architectural proposal. Return JSON with keys `output` (your "
        "proposal) and `status` (one of DONE, DONE_WITH_CONCERNS, "
        "NEEDS_CONTEXT, BLOCKED)."
    ),
    Phase.SPEC: (
        "You are the Architect agent in the spec phase. Write requirements "
        "entities from the prior brainstorm. Return JSON with keys `output` "
        "(entity drafts) and `status`."
    ),
    Phase.PLAN: (
        "You are the Planner agent. Decompose the spec into ordered, "
        "testable steps; declare the validation artifact for each step. "
        "Return JSON with keys `output` (step list) and `status`."
    ),
    Phase.GENERATE: (
        "You are the Implementer agent. Produce the artifacts per the plan, "
        "honouring Gate B (validation artifact must exist and run red first). "
        "Return JSON with keys `output` (artifact set) and `status`."
    ),
    Phase.REVIEW: (
        "You are a reviewer agent (spec compliance + quality). Evaluate "
        "artifacts against the spec and the quality rules. Return JSON with "
        "keys `output` (findings) and `status`."
    ),
}


_AGENT_FOR_PHASE: dict[Phase, AgentRole] = {
    Phase.BRAINSTORM: AgentRole.ARCHITECT,
    Phase.SPEC: AgentRole.ARCHITECT,
    Phase.PLAN: AgentRole.PLANNER,
    Phase.GENERATE: AgentRole.IMPLEMENTER,
    Phase.REVIEW: AgentRole.SPEC_REVIEWER,
}


def agent_for_phase(phase: Phase) -> AgentRole:
    """Helper: default agent role for a given phase."""
    return _AGENT_FOR_PHASE[phase]


class InProcessDispatcher:
    """Runs agents in-process by delegating to the C8 LLM gateway.

    The dispatcher is deliberately thin — it converts a `DispatchRequest`
    into an OpenAI-compatible chat completion, hits C8, and parses the
    JSON envelope the agent is expected to return. Error paths collapse
    onto `EscalationStatus.BLOCKED` so the orchestrator always receives
    a well-formed completion.
    """

    def __init__(self, llm_client: LLMGatewayClient) -> None:
        self._llm = llm_client

    async def dispatch(self, request: DispatchRequest) -> AgentCompletion:
        system = _SYSTEM_PROMPTS[request.phase]
        user = _build_user_prompt(request)
        started = time.monotonic()

        try:
            response = await self._llm.chat_completion(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(role=ChatRole.SYSTEM, content=system),
                        ChatMessage(role=ChatRole.USER, content=user),
                    ],
                    # `response_format={type:json_object}` leans on structured
                    # outputs where the provider supports it (R-800-041).
                    response_format={"type": "json_object"},
                ),
                agent_name=request.agent.value,
                session_id=request.session_id,
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                phase=request.phase.value,
            )
        except Exception as exc:  # deliberately broad — any failure is BLOCKED
            return AgentCompletion(
                agent=request.agent,
                run_id=request.run_id,
                phase=request.phase,
                status=EscalationStatus.BLOCKED,
                blocker=AgentBlocker(
                    reason=f"LLM gateway error: {type(exc).__name__}: {exc}"[:500]
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        call_id = response.id or ""

        # Extract the assistant message content and interpret it as the
        # structured envelope the system prompt asked for.
        try:
            content = _extract_assistant_text(response.choices[0].message.content)
            parsed = json.loads(content) if content else {}
        except (json.JSONDecodeError, IndexError, AttributeError) as exc:
            return AgentCompletion(
                agent=request.agent,
                run_id=request.run_id,
                phase=request.phase,
                status=EscalationStatus.BLOCKED,
                blocker=AgentBlocker(
                    reason=f"agent response not parseable JSON: {exc}",
                ),
                duration_ms=duration_ms,
                llm_call_ids=[call_id] if call_id else [],
            )

        return _parse_completion(parsed, request, duration_ms, call_id)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(request: DispatchRequest) -> str:
    bundle = json.dumps(request.context_bundle, indent=2, default=str)
    return (
        f"Phase: {request.phase.value}\n"
        f"Agent: {request.agent.value}\n\n"
        f"User prompt:\n{request.prompt}\n\n"
        f"Context bundle (JSON):\n{bundle}"
    )


def _extract_assistant_text(content: Any) -> str:
    """OpenAI messages allow `content` to be str OR list[dict]. We accept
    both and join any text parts so that providers returning structured
    content blocks work transparently."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _parse_completion(
    parsed: dict[str, Any],
    request: DispatchRequest,
    duration_ms: int,
    call_id: str,
) -> AgentCompletion:
    """Map the agent's JSON envelope onto AgentCompletion.

    Tolerates partial payloads — missing `status` defaults to BLOCKED so
    a malformed agent response cannot silently advance the pipeline.
    """
    status_raw = str(parsed.get("status", "")).upper().strip()
    try:
        status = EscalationStatus(status_raw)
    except ValueError:
        return AgentCompletion(
            agent=request.agent,
            run_id=request.run_id,
            phase=request.phase,
            status=EscalationStatus.BLOCKED,
            blocker=AgentBlocker(
                reason=f"agent returned unknown status: {status_raw!r}",
            ),
            duration_ms=duration_ms,
            llm_call_ids=[call_id] if call_id else [],
        )

    output = parsed.get("output")
    output_dict: dict[str, Any] = output if isinstance(output, dict) else {"raw": output}

    concerns = [
        AgentConcern(**c)
        for c in (parsed.get("concerns") or [])
        if isinstance(c, dict) and "message" in c and "severity" in c
    ]

    needs_context: AgentNeedsContext | None = None
    if status == EscalationStatus.NEEDS_CONTEXT:
        queries = parsed.get("needs_context", {}).get("queries", [])
        needs_context = AgentNeedsContext(
            queries=[q for q in queries if isinstance(q, str)]
        )

    blocker: AgentBlocker | None = None
    if status == EscalationStatus.BLOCKED:
        blocker_payload = parsed.get("blocker") or {}
        blocker = AgentBlocker(
            reason=str(blocker_payload.get("reason", "unspecified")),
            suggested_action=blocker_payload.get("suggested_action"),
        )

    return AgentCompletion(
        agent=request.agent,
        run_id=request.run_id,
        phase=request.phase,
        status=status,
        output=output_dict,
        concerns=concerns,
        needs_context=needs_context,
        blocker=blocker,
        duration_ms=duration_ms,
        llm_call_ids=[call_id] if call_id else [],
    )
