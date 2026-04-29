# =============================================================================
# File: main.py
# Version: 3
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/main.py
# Description: FastAPI app factory for C3 Conversation Service.
#
#              v3 (2026-04-28): wires `RemoteMemoryService` + the C8
#              `LLMGatewayClient` automatically when the corresponding
#              env vars are present (`C3_C7_BASE_URL`, `C8_GATEWAY_URL`).
#              In K8s the Deployment ConfigMap supplies these → C3
#              starts in chat-with-RAG mode. In tests / dev where the
#              env vars are unset, C3 falls back to the legacy stub
#              path (no RAG, fixed reply) — same behaviour as v2.
#
#              v2: env-var single-source refactor. Arango connection
#              params read from unprefixed shared vars via
#              validation_alias.
#
# @relation implements:R-100-114
# @relation implements:R-100-110
# @relation implements:R-100-111
# @relation implements:R-100-117
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ay_platform_core.c3_conversation.db.repository import ConversationRepository
from ay_platform_core.c3_conversation.router import router
from ay_platform_core.c3_conversation.service import ConversationService
from ay_platform_core.c7_memory.remote import RemoteMemoryService
from ay_platform_core.c8_llm.client import LLMGatewayClient
from ay_platform_core.c8_llm.config import ClientSettings
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
from ay_platform_core.observability.auth_guard import AuthGuardMiddleware
from ay_platform_core.observability.config import LoggingSettings


class ConversationConfig(BaseSettings):
    """C3 runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="c3_", extra="ignore", populate_by_name=True
    )

    # Shared (read without prefix via validation_alias)
    arango_url: str = Field(
        default="http://arangodb:8529", validation_alias="ARANGO_URL"
    )
    arango_db: str = Field(default="platform", validation_alias="ARANGO_DB")
    arango_username: str = Field(default="ay_app", validation_alias="ARANGO_USERNAME")
    arango_password: str = Field(
        default="changeme", validation_alias="ARANGO_PASSWORD"
    )

    # C3-specific — RAG wiring. Empty → C3 boots in stub-chat mode
    # (legacy v2 behaviour). Set → RemoteMemoryService is wired and,
    # combined with a non-empty `C8_GATEWAY_URL` (read separately via
    # `ClientSettings()`), chat-with-RAG is active.
    c7_base_url: str = ""
    """Base URL of the C7 Memory Service (e.g.
    `http://c7-memory.aywizz.svc.cluster.local:8000` in K8s). Empty →
    no RAG retrieval, ConversationService runs the stub fallback."""

    # C8 connection params are owned by `ClientSettings` (c8_llm.config)
    # — that class already reads `C8_GATEWAY_URL` and the timeouts via
    # validation_alias, and is the single source of truth across
    # C3 / C4 / any other component using C8. Adding a duplicate field
    # here would collide on `C8_GATEWAY_URL` (caught by the env
    # completeness coherence test).

    c8_bearer_token: str = ""
    """Bearer token sent on every C8 request. Read as
    `C3_C8_BEARER_TOKEN` (env_prefix `c3_`); empty → "no-auth"
    placeholder is sent (mock_llm accepts any non-empty Bearer; real
    LiteLLM expects a real key)."""


def create_app(config: ConversationConfig | None = None) -> FastAPI:
    cfg = config or ConversationConfig()
    log_cfg = LoggingSettings()
    configure_logging(component="c3_conversation", settings=log_cfg)
    client = ArangoClient(hosts=cfg.arango_url)
    db = client.db(
        cfg.arango_db, username=cfg.arango_username, password=cfg.arango_password
    )
    repo = ConversationRepository(db)

    # Optional RAG wiring — both C7 base URL and C8 gateway URL must
    # resolve. Either missing → ConversationService.send_message_stream
    # falls back to the deterministic stub reply.
    memory_service: RemoteMemoryService | None = None
    llm_client: LLMGatewayClient | None = None
    c8_settings = ClientSettings()  # reads C8_GATEWAY_URL + timeouts from env
    if cfg.c7_base_url and c8_settings.gateway_url:
        memory_service = RemoteMemoryService(cfg.c7_base_url)
        llm_client = LLMGatewayClient(
            c8_settings,
            bearer_token=cfg.c8_bearer_token or "no-auth",
        )

    service = ConversationService(
        repo, memory_service=memory_service, llm_client=llm_client,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        yield
        # Best-effort close of the remote httpx clients we own.
        if memory_service is not None:
            await memory_service.aclose()
        if llm_client is not None:
            await llm_client.aclose()

    app = FastAPI(title="C3 Conversation Service", lifespan=lifespan)
    # Order matters in Starlette: last added = outermost. We want
    # TraceContext to run FIRST (so AuthGuard's reject log carries
    # trace_id), so AuthGuard is added FIRST (innermost).
    app.add_middleware(AuthGuardMiddleware, component="c3_conversation")
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router)
    app.state.conversation_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c3_conversation"}

    return app


app = create_app()
