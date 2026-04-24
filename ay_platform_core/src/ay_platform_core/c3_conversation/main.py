# =============================================================================
# File: main.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/main.py
# Description: FastAPI app factory for C3 Conversation Service.
#
# @relation implements:R-100-114
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from ay_platform_core.c3_conversation.db.repository import ConversationRepository
from ay_platform_core.c3_conversation.router import router
from ay_platform_core.c3_conversation.service import ConversationService


class ConversationConfig(BaseSettings):
    """C3 runtime settings."""

    model_config = SettingsConfigDict(env_prefix="c3_", extra="ignore")

    arango_host: str = "arangodb"
    arango_port: int = 8529
    arango_db: str = "platform"
    arango_user: str = "root"
    arango_password: str = "password"


def create_app(config: ConversationConfig | None = None) -> FastAPI:
    cfg = config or ConversationConfig()
    client = ArangoClient(hosts=f"http://{cfg.arango_host}:{cfg.arango_port}")
    db = client.db(cfg.arango_db, username=cfg.arango_user, password=cfg.arango_password)
    repo = ConversationRepository(db)
    service = ConversationService(repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        yield

    app = FastAPI(title="C3 Conversation Service", lifespan=lifespan)
    app.include_router(router)
    app.state.conversation_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c3_conversation"}

    return app


app = create_app()
