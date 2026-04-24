# =============================================================================
# File: conftest.py
# Version: 1
# Path: ay_platform_core/tests/integration/c4_orchestrator/conftest.py
# Description: Fixtures for C4 integration tests. Uses REAL ArangoDB and
#              REAL C8 client, but the LiteLLM proxy is impersonated by a
#              FastAPI ASGI mock that returns scripted completions — this
#              gives us reproducibility without a real LLM provider key.
#              Per session directive: integration tests use real
#              components wherever possible.
# =============================================================================

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI, Header, HTTPException, Request

from ay_platform_core.c4_orchestrator.config import OrchestratorConfig
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository
from ay_platform_core.c4_orchestrator.dispatcher.in_process import InProcessDispatcher
from ay_platform_core.c4_orchestrator.domains.code.plugin import CodeDomainPlugin
from ay_platform_core.c4_orchestrator.events.null_publisher import NullPublisher
from ay_platform_core.c4_orchestrator.router import router
from ay_platform_core.c4_orchestrator.service import OrchestratorService
from ay_platform_core.c8_llm.client import LLMGatewayClient
from ay_platform_core.c8_llm.config import ClientSettings
from tests.fixtures.containers import ArangoEndpoint, cleanup_arango_database

# ---------------------------------------------------------------------------
# Scripted LiteLLM mock
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """FIFO queue of canned agent responses.

    The test sets `enqueue(payload)` for each expected agent invocation.
    The mock ASGI app dequeues one entry per chat/completions call and
    returns it as the assistant content. Exhausting the queue yields a
    generic error so test authors see why a call wasn't scripted.
    """

    def __init__(self) -> None:
        self._responses: list[dict[str, Any]] = []
        self.calls_seen: list[dict[str, Any]] = []

    def enqueue(self, payload: dict[str, Any]) -> None:
        self._responses.append(payload)

    def next_response(self) -> dict[str, Any]:
        if not self._responses:
            return {
                "status": "BLOCKED",
                "output": {},
                "blocker": {"reason": "no scripted response left in ScriptedLLM queue"},
            }
        return self._responses.pop(0)


@pytest.fixture(scope="function")
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture(scope="function")
def mock_llm_app(scripted_llm: ScriptedLLM) -> FastAPI:
    """Minimal ASGI app shaped like the C8 proxy. Accepts any path,
    returns the next scripted envelope as the assistant content."""
    app = FastAPI()

    @app.post("/v1/chat/completions", response_model=None)
    async def completions(
        request: Request,
        x_agent_name: str | None = Header(default=None),
        x_session_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="bearer required")
        if not x_agent_name or not x_session_id:
            raise HTTPException(status_code=400, detail="missing tags")
        body = await request.json()
        scripted_llm.calls_seen.append(body)
        envelope = scripted_llm.next_response()
        return {
            "id": f"mock-{len(scripted_llm.calls_seen)}",
            "object": "chat.completion",
            "created": 1_700_000_000,
            "model": body.get("model") or "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(envelope),
                    },
                    "finish_reason": "stop",
                },
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    return app


# ---------------------------------------------------------------------------
# Real storage + orchestrator wiring
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def c4_repo(arango_container: ArangoEndpoint) -> Iterator[OrchestratorRepository]:
    db_name = f"c4_test_{uuid.uuid4().hex[:8]}"
    client = ArangoClient(hosts=arango_container.url)
    sys_db = client.db("_system", username="root", password=arango_container.password)
    sys_db.create_database(db_name)
    try:
        db = client.db(db_name, username="root", password=arango_container.password)
        repo = OrchestratorRepository(db)
        repo._ensure_collections_sync()
        yield repo
    finally:
        cleanup_arango_database(arango_container, db_name)


@pytest_asyncio.fixture(scope="function")
async def c4_llm_client(mock_llm_app: FastAPI) -> AsyncIterator[LLMGatewayClient]:
    transport = httpx.ASGITransport(app=mock_llm_app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://mock/v1")
    client = LLMGatewayClient(
        ClientSettings(gateway_url="http://mock/v1"),
        bearer_token="test-token",
        http_client=http_client,
    )
    try:
        yield client
    finally:
        await http_client.aclose()


@pytest.fixture(scope="function")
def c4_publisher() -> NullPublisher:
    return NullPublisher()


@pytest_asyncio.fixture(scope="function")
async def c4_service(
    c4_repo: OrchestratorRepository,
    c4_llm_client: LLMGatewayClient,
    c4_publisher: NullPublisher,
) -> OrchestratorService:
    return OrchestratorService(
        config=OrchestratorConfig(),
        repo=c4_repo,
        dispatcher=InProcessDispatcher(c4_llm_client),
        domain_plugin=CodeDomainPlugin(),
        publisher=c4_publisher,
    )


@pytest.fixture(scope="function")
def c4_app(c4_service: OrchestratorService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.orchestrator_service = c4_service
    return app
