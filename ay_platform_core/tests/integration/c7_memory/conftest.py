# =============================================================================
# File: conftest.py
# Version: 1
# Path: ay_platform_core/tests/integration/c7_memory/conftest.py
# Description: Fixtures for C7 integration tests. Real ArangoDB via
#              testcontainers, real deterministic embedder (no ML dep), C7
#              service wired in-process.
# =============================================================================

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.deterministic import DeterministicHashEmbedder
from ay_platform_core.c7_memory.router import router
from ay_platform_core.c7_memory.service import MemoryService
from tests.fixtures.containers import ArangoEndpoint, cleanup_arango_database


@pytest.fixture(scope="function")
def c7_repo(arango_container: ArangoEndpoint) -> Iterator[MemoryRepository]:
    db_name = f"c7_test_{uuid.uuid4().hex[:8]}"
    client = ArangoClient(hosts=arango_container.url)
    sys_db = client.db("_system", username="root", password=arango_container.password)
    sys_db.create_database(db_name)
    try:
        db = client.db(db_name, username="root", password=arango_container.password)
        repo = MemoryRepository(db)
        repo._ensure_collections_sync()
        yield repo
    finally:
        cleanup_arango_database(arango_container, db_name)


@pytest.fixture(scope="function")
def c7_embedder() -> DeterministicHashEmbedder:
    return DeterministicHashEmbedder(dimension=64)


@pytest.fixture(scope="function")
def c7_config() -> MemoryConfig:
    return MemoryConfig(
        embedding_dimension=64,
        chunk_token_size=20,
        chunk_overlap=4,
        default_quota_bytes=1024 * 1024,  # 1 MiB for tests
        retrieval_scan_cap=1000,
    )


@pytest.fixture(scope="function")
def c7_service(
    c7_config: MemoryConfig,
    c7_repo: MemoryRepository,
    c7_embedder: DeterministicHashEmbedder,
) -> MemoryService:
    return MemoryService(config=c7_config, repo=c7_repo, embedder=c7_embedder)


@pytest.fixture(scope="function")
def c7_app(c7_service: MemoryService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.memory_service = c7_service
    return app
