# =============================================================================
# File: main.py
# Version: 4
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/main.py
# Description: FastAPI app factory for C4 Orchestrator. Wires the in-process
#              dispatcher backed by a real C8 LLM client (the C8 URL is read
#              from C4_LLM_GATEWAY_URL).
#
#              v4: mounts `documents_router` — the chat-direct DocGen
#              document CRUD surface (D-015 / R-200-153..156).
#              v3: passes the `ArtifactsService` instance into the
#              `OrchestratorService` so the generate phase materialises
#              its `output.files` into the artifacts surface and triggers
#              the Gitea push on completion (R-200-150..152).
#              v2: mounts the project-artifacts surface
#              (`artifacts_router`) under
#              `/api/v1/projects/{pid}/artifacts/*` + instantiates
#              the `ArtifactsService` over the shared MinIO client and
#              the orchestrator repository (which gains the
#              `c4_artifact_runs` collection). Lifespan ensures the
#              bucket exists at startup so a fresh dev stack just
#              works.
#
# @relation implements:R-100-114
# @relation implements:R-200-131
# @relation implements:R-200-151
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from minio import Minio

from ay_platform_core.c2_auth.gitea_client import GiteaClient
from ay_platform_core.c4_orchestrator.artifacts_router import (
    router as artifacts_router,
)
from ay_platform_core.c4_orchestrator.artifacts_service import ArtifactsService
from ay_platform_core.c4_orchestrator.artifacts_storage import ArtifactStorage
from ay_platform_core.c4_orchestrator.config import OrchestratorConfig
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository
from ay_platform_core.c4_orchestrator.dispatcher.in_process import InProcessDispatcher
from ay_platform_core.c4_orchestrator.documents_router import (
    router as documents_router,
)
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
from ay_platform_core.observability.auth_guard import AuthGuardMiddleware
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

    # MinIO client + artifacts service. Same bucket (`orchestrator`)
    # as the existing run state ; artifacts live under the
    # `c4-artifacts/` prefix (R-200-130) — clear separation from the
    # `c4-runs/` prefix that holds orchestrator internal state.
    minio_client = Minio(
        cfg.minio_endpoint,
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        secure=cfg.minio_secure,
    )
    artifact_storage = ArtifactStorage(minio_client, cfg.minio_bucket)
    # Gitea client — wired when `C4_GITEA_BASE_URL` is non-empty.
    # Pushes artifacts at run completion (R-200-146) AND backs the
    # `/git/commits` proxy (R-200-147).
    gitea: GiteaClient | None = None
    if cfg.gitea_base_url:
        gitea = GiteaClient(
            base_url=cfg.gitea_base_url,
            admin_username=cfg.gitea_admin_username,
            admin_password=cfg.gitea_admin_password,
        )
    artifacts_service = ArtifactsService(
        repo=repo, storage=artifact_storage, gitea=gitea,
    )

    service = OrchestratorService(
        config=cfg,
        repo=repo,
        dispatcher=InProcessDispatcher(llm_client),
        domain_plugin=CodeDomainPlugin(),
        publisher=NullPublisher(),
        artifacts_service=artifacts_service,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        # Idempotent ; covers the rare case of a fresh MinIO bucket.
        await artifact_storage.ensure_bucket()
        yield
        await llm_client.aclose()
        if gitea is not None:
            await gitea.aclose()

    app = FastAPI(title="C4 Orchestrator", lifespan=lifespan)
    app.add_middleware(AuthGuardMiddleware, component="c4_orchestrator")
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router)
    app.include_router(artifacts_router)
    app.include_router(documents_router)
    app.state.orchestrator_service = service
    app.state.artifacts_service = artifacts_service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c4_orchestrator"}

    return app


app = create_app()
