# =============================================================================
# File: main.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/main.py
# Description: FastAPI app factory for C3 Conversation Service.
#
#              v2: env-var single-source refactor. Arango connection params
#              are read from unprefixed shared vars (`ARANGO_URL`, `ARANGO_DB`,
#              `ARANGO_USERNAME`, `ARANGO_PASSWORD`) via validation_alias.
#              C3 has no per-component knobs at the moment; the Settings
#              class only carries the shared block.
#
# @relation implements:R-100-114
# @relation implements:R-100-110
# @relation implements:R-100-111
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
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
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


def create_app(config: ConversationConfig | None = None) -> FastAPI:
    cfg = config or ConversationConfig()
    log_cfg = LoggingSettings()
    configure_logging(component="c3_conversation", settings=log_cfg)
    client = ArangoClient(hosts=cfg.arango_url)
    db = client.db(
        cfg.arango_db, username=cfg.arango_username, password=cfg.arango_password
    )
    repo = ConversationRepository(db)
    service = ConversationService(repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        yield

    app = FastAPI(title="C3 Conversation Service", lifespan=lifespan)
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router)
    app.state.conversation_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c3_conversation"}

    return app


app = create_app()
