# =============================================================================
# File: test_dispatcher.py
# Version: 1
# Path: ay_platform_core/tests/unit/c4_orchestrator/test_dispatcher.py
# Description: Unit tests for the in-process agent dispatcher. Mocks the
#              C8 gateway client (AsyncMock) to exercise response parsing
#              and the error-to-BLOCKED collapse paths.
# =============================================================================

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ay_platform_core.c4_orchestrator.dispatcher.base import DispatchRequest
from ay_platform_core.c4_orchestrator.dispatcher.in_process import (
    InProcessDispatcher,
    agent_for_phase,
)
from ay_platform_core.c4_orchestrator.models import (
    AgentRole,
    EscalationStatus,
    Phase,
)


def _request(phase: Phase = Phase.PLAN) -> DispatchRequest:
    return DispatchRequest(
        run_id="run-1",
        phase=phase,
        agent=agent_for_phase(phase),
        session_id="s-1",
        tenant_id="t-1",
        user_id="u-1",
        project_id="p-1",
        prompt="do the thing",
        context_bundle={"domain": "code"},
    )


def _mock_response(content: dict[str, Any]) -> Any:
    """Build an object that duck-types ChatCompletionResponse enough for
    the dispatcher's consumption."""

    class _Msg:
        def __init__(self, c: str) -> None:
            self.content = c

    class _Choice:
        def __init__(self, c: str) -> None:
            self.message = _Msg(c)

    class _Resp:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.id = "call-xyz"
            self.choices = [_Choice(json.dumps(payload))]

    return _Resp(content)


@pytest.mark.unit
class TestAgentForPhase:
    def test_brainstorm_is_architect(self) -> None:
        assert agent_for_phase(Phase.BRAINSTORM) == AgentRole.ARCHITECT

    def test_plan_is_planner(self) -> None:
        assert agent_for_phase(Phase.PLAN) == AgentRole.PLANNER

    def test_generate_is_implementer(self) -> None:
        assert agent_for_phase(Phase.GENERATE) == AgentRole.IMPLEMENTER


@pytest.mark.unit
@pytest.mark.asyncio
class TestDispatcherHappyPath:
    async def test_done_completion_parsed(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = _mock_response({
            "status": "DONE",
            "output": {"steps": [1, 2, 3]},
        })
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.DONE
        assert completion.output == {"steps": [1, 2, 3]}
        assert completion.llm_call_ids == ["call-xyz"]

    async def test_done_with_concerns_parsed(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = _mock_response({
            "status": "DONE_WITH_CONCERNS",
            "output": {},
            "concerns": [
                {"severity": "medium", "message": "cold-start latency"},
            ],
        })
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.DONE_WITH_CONCERNS
        assert len(completion.concerns) == 1
        assert completion.concerns[0].severity == "medium"

    async def test_needs_context_parsed(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = _mock_response({
            "status": "NEEDS_CONTEXT",
            "output": {},
            "needs_context": {"queries": ["how many users?", "what db?"]},
        })
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.NEEDS_CONTEXT
        assert completion.needs_context is not None
        assert len(completion.needs_context.queries) == 2

    async def test_blocked_parsed(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = _mock_response({
            "status": "BLOCKED",
            "output": {},
            "blocker": {"reason": "ambiguous spec", "suggested_action": "clarify"},
        })
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.BLOCKED
        assert completion.blocker is not None
        assert completion.blocker.reason == "ambiguous spec"


@pytest.mark.unit
@pytest.mark.asyncio
class TestDispatcherErrorPaths:
    async def test_gateway_exception_collapsed_to_blocked(self) -> None:
        client = AsyncMock()
        client.chat_completion.side_effect = RuntimeError("bad gateway")
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.BLOCKED
        assert completion.blocker is not None
        assert "LLM gateway error" in completion.blocker.reason

    async def test_unknown_status_collapsed_to_blocked(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = _mock_response({
            "status": "MAYBE_OK",
            "output": {},
        })
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.BLOCKED
        assert completion.blocker is not None
        assert "unknown status" in completion.blocker.reason

    async def test_malformed_json_collapsed_to_blocked(self) -> None:
        client = AsyncMock()

        class _Msg:
            content = "not json at all"

        class _Choice:
            message = _Msg()

        class _Resp:
            id = "call-bad"

            def __init__(self) -> None:
                self.choices = [_Choice()]

        client.chat_completion.return_value = _Resp()
        dispatcher = InProcessDispatcher(client)
        completion = await dispatcher.dispatch(_request())
        assert completion.status == EscalationStatus.BLOCKED
        assert completion.blocker is not None
        assert "parseable JSON" in completion.blocker.reason
