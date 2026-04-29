# =============================================================================
# File: main.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c6_validation/main.py
# Description: FastAPI app factory for C6 Validation Pipeline Registry.
#
# @relation implements:R-100-114
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from minio import Minio

# Importing the package triggers registration of the built-in `code` plugin
# (R-700-002 — build-time discovery).
import ay_platform_core.c6_validation  # noqa: F401
from ay_platform_core.c6_validation.config import ValidationConfig
from ay_platform_core.c6_validation.db.repository import ValidationRepository
from ay_platform_core.c6_validation.plugin.registry import get_registry
from ay_platform_core.c6_validation.router import router
from ay_platform_core.c6_validation.service import ValidationService
from ay_platform_core.c6_validation.storage.minio_storage import (
    ValidationSnapshotStorage,
)
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
from ay_platform_core.observability.auth_guard import AuthGuardMiddleware
from ay_platform_core.observability.config import LoggingSettings


def create_app(config: ValidationConfig | None = None) -> FastAPI:
    cfg = config or ValidationConfig()
    log_cfg = LoggingSettings()
    configure_logging(component="c6_validation", settings=log_cfg)
    arango_client = ArangoClient(hosts=cfg.arango_url)
    db = arango_client.db(
        cfg.arango_db, username=cfg.arango_username, password=cfg.arango_password
    )
    repo = ValidationRepository(db)

    minio_client = Minio(
        cfg.minio_endpoint,
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        secure=cfg.minio_secure,
    )
    snapshot_store = ValidationSnapshotStorage(minio_client, cfg.minio_bucket)

    service = ValidationService(
        config=cfg,
        registry=get_registry(),
        repo=repo,
        snapshot_store=snapshot_store,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        snapshot_store._ensure_bucket_sync()
        yield

    app = FastAPI(title="C6 Validation Pipeline Registry", lifespan=lifespan)
    # `/api/v1/validation/health` is a public status endpoint that
    # K8s probes / smoke tests hit without auth — exempt explicitly.
    # In K8s, Traefik forward-auth still gates it at the edge.
    app.add_middleware(
        AuthGuardMiddleware,
        component="c6_validation",
        exempt_prefixes=["/health", "/api/v1/validation/health"],
    )
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router)
    app.state.validation_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c6_validation"}

    return app


app = create_app()
