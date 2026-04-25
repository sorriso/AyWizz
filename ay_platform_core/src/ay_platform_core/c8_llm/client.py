# =============================================================================
# File: client.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c8_llm/client.py
# Description: Python client for the C8 LLM gateway. All internal components
#              (C3, C4, C6, C7, …) use this class rather than importing
#              LiteLLM directly (R-800-011 policy). Enforces the mandatory
#              agent/session headers (R-800-013) at the call site so no
#              component can accidentally bypass cost attribution.
#
# @relation implements:R-800-010
# @relation implements:R-800-011
# @relation implements:R-800-013
# @relation implements:R-800-014
# @relation implements:R-800-073
# =============================================================================

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from ay_platform_core.c8_llm.config import ClientSettings
from ay_platform_core.observability import make_traced_client
from ay_platform_core.c8_llm.models import (
    BudgetStatus,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CostSummary,
)


class LLMGatewayError(RuntimeError):
    """Raised on any non-success response from the gateway."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"LLM gateway returned {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class LLMGatewayClient:
    """HTTP client for the C8 LiteLLM proxy.

    Every call propagates the mandatory headers `X-Agent-Name` and
    `X-Session-Id` (R-800-013). Optional headers (`X-Phase`,
    `X-Sub-Agent-Id`, `X-Cache-Hint`) are provided as kwargs so callers
    opt in explicitly. The bearer token is either injected at construction
    or per-call; keeping it per-call accommodates user-scoped JWT forwarding.
    """

    def __init__(
        self,
        settings: ClientSettings,
        *,
        bearer_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._default_bearer = bearer_token
        # Reuse caller-provided client (e.g. from FastAPI app state) so that
        # connection pooling is shared. Otherwise spawn a dedicated client
        # and close it via `aclose()`.
        self._owned_client = http_client is None
        self._client = http_client or make_traced_client(
            base_url=settings.gateway_url,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Chat completions
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        payload: ChatCompletionRequest,
        *,
        agent_name: str,
        session_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
        phase: str | None = None,
        sub_agent_id: str | None = None,
        cache_hint: str | None = None,
        bearer_token: str | None = None,
    ) -> ChatCompletionResponse:
        """Non-streaming chat completion.

        `agent_name` and `session_id` are required — their absence at the
        Python layer catches the mistake before the gateway does.
        """
        if payload.stream:
            raise ValueError(
                "chat_completion() does not support streaming payloads; "
                "call chat_completion_stream() instead"
            )
        headers = self._headers(
            agent_name=agent_name,
            session_id=session_id,
            tenant_id=tenant_id,
            project_id=project_id,
            phase=phase,
            sub_agent_id=sub_agent_id,
            cache_hint=cache_hint,
            bearer_token=bearer_token,
        )
        resp = await self._client.post(
            "/chat/completions",
            json=payload.model_dump(exclude_none=True),
            headers=headers,
        )
        if resp.status_code != 200:
            raise LLMGatewayError(resp.status_code, resp.text)
        return ChatCompletionResponse.model_validate(resp.json())

    @asynccontextmanager
    async def chat_completion_stream(
        self,
        payload: ChatCompletionRequest,
        *,
        agent_name: str,
        session_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
        phase: str | None = None,
        sub_agent_id: str | None = None,
        cache_hint: str | None = None,
        bearer_token: str | None = None,
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Streaming chat completion — yields OpenAI-style SSE chunks.

        Used as an async context manager to guarantee the underlying
        connection is released even when the caller cancels early.
        """
        stream_payload = payload.model_copy(update={"stream": True})
        headers = self._headers(
            agent_name=agent_name,
            session_id=session_id,
            tenant_id=tenant_id,
            project_id=project_id,
            phase=phase,
            sub_agent_id=sub_agent_id,
            cache_hint=cache_hint,
            bearer_token=bearer_token,
        )
        req = self._client.build_request(
            "POST",
            "/chat/completions",
            json=stream_payload.model_dump(exclude_none=True),
            headers=headers,
        )
        resp = await self._client.send(req, stream=True)
        try:
            if resp.status_code != 200:
                body = await resp.aread()
                raise LLMGatewayError(resp.status_code, body.decode("utf-8", "replace"))
            yield _sse_event_iterator(resp)
        finally:
            await resp.aclose()

    # ------------------------------------------------------------------
    # Admin surface — cost + budget
    # ------------------------------------------------------------------

    async def cost_summary(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        bearer_token: str | None = None,
    ) -> CostSummary:
        """GET /admin/v1/costs/summary — aggregated cost for a tenant/project."""
        params: dict[str, str] = {"tenant_id": tenant_id}
        if project_id:
            params["project_id"] = project_id
        resp = await self._client.get(
            "/admin/v1/costs/summary",
            params=params,
            headers=self._auth_headers(bearer_token),
        )
        if resp.status_code != 200:
            raise LLMGatewayError(resp.status_code, resp.text)
        return CostSummary.model_validate(resp.json())

    async def budget_status(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        bearer_token: str | None = None,
    ) -> BudgetStatus:
        """GET /admin/v1/budgets — current consumption vs cap."""
        params: dict[str, str] = {"tenant_id": tenant_id}
        if project_id:
            params["project_id"] = project_id
        resp = await self._client.get(
            "/admin/v1/budgets",
            params=params,
            headers=self._auth_headers(bearer_token),
        )
        if resp.status_code != 200:
            raise LLMGatewayError(resp.status_code, resp.text)
        return BudgetStatus.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Header assembly
    # ------------------------------------------------------------------

    def _headers(
        self,
        *,
        agent_name: str,
        session_id: str,
        tenant_id: str | None,
        project_id: str | None,
        phase: str | None,
        sub_agent_id: str | None,
        cache_hint: str | None,
        bearer_token: str | None,
    ) -> dict[str, str]:
        if not agent_name:
            raise ValueError("X-Agent-Name is mandatory (R-800-013)")
        if not session_id:
            raise ValueError("X-Session-Id is mandatory (R-800-013)")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Agent-Name": agent_name,
            "X-Session-Id": session_id,
        }
        headers.update(self._auth_headers(bearer_token))
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        if project_id:
            headers["X-Project-Id"] = project_id
        if phase:
            headers["X-Phase"] = phase
        if sub_agent_id:
            headers["X-Sub-Agent-Id"] = sub_agent_id
        if cache_hint:
            if cache_hint not in {"static", "dynamic", "none"}:
                raise ValueError(
                    f"X-Cache-Hint must be static|dynamic|none, got {cache_hint!r}"
                )
            headers["X-Cache-Hint"] = cache_hint
        return headers

    def _auth_headers(self, bearer_token: str | None) -> dict[str, str]:
        token = bearer_token or self._default_bearer
        if not token:
            raise ValueError("bearer token is required (R-800-012)")
        return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# SSE decoding helper — translates OpenAI-compatible SSE to dict chunks
# ---------------------------------------------------------------------------


async def _sse_event_iterator(
    response: httpx.Response,
) -> AsyncIterator[dict[str, Any]]:
    """Parse a streaming response in OpenAI SSE format.

    Emits one dict per `data:` event. Terminates on the `[DONE]` sentinel.
    Comments (heartbeat lines) and empty lines are skipped.
    """
    async for raw_line in response.aiter_lines():
        line = raw_line.strip()
        if not line or line.startswith(":"):  # comment / heartbeat
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LLMGatewayError(200, f"malformed SSE chunk: {payload!r}") from exc
