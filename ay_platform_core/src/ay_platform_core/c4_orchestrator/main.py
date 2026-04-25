# =============================================================================
# File: main.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/main.py
# Description: FastAPI app factory for C4 Orchestrator. Wires the in-process
#              dispatcher backed by a real C8 LLM client (the C8 URL is read
#              from C4_LLM_GATEWAY_URL).
#
# @relation implements:R-100-114
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI

from ay_platform_core.c4_orchestrator.config import OrchestratorConfig
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository
from ay_platform_core.c4_orchestrator.dispatcher.in_process import InProcessDispatcher
from ay_platform_core.c4_orchestrator.domains.code.plugin import CodeDomainPlugin
from ay_platform_core.c4_orchestrator.events.null_publisher import NullPublisher
from ay_platform_core.c4_orchestrator.router import router
from ay_platform_core.c4_orchestrator.service import OrchestratorService
from ay_platform_core.c8_llm.client import LLMGatewayClient
from ay_platform_core.c8_llm.config import ClientSettings
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
from ay_platform_core.observability.config import LoggingSettings


def create_app(config: OrchestratorConfig | None = None) -> FastAPI:
    cfg = config or OrchestratorConfig()
    log_cfg = LoggingSettings()
    configure_logging(component="c4_orchestrator", settings=log_cfg)
    arango_client = ArangoClient(hosts=cfg.arango_url)
    db = arango_client.db(
        cfg.arango_db, username=cfg.arango_username, password=cfg.arango_password
    )
    repo = OrchestratorRepository(db)

    llm_settings = ClientSettings()
    llm_client = LLMGatewayClient(llm_settings, bearer_token="c4-orchestrator")

    service = OrchestratorService(
        config=cfg,
        repo=repo,
        dispatcher=InProcessDispatcher(llm_client),
        domain_plugin=CodeDomainPlugin(),
        publisher=NullPublisher(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        yield
        await llm_client.aclose()

    app = FastAPI(title="C4 Orchestrator", lifespan=lifespan)
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router)
    app.state.orchestrator_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c4_orchestrator"}

    return app


app = create_app()
