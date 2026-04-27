# =============================================================================
# File: conftest.py
# Version: 2
# Path: ay_platform_core/tests/integration/c7_memory/conftest.py
# Description: Fixtures for C7 integration tests.
#              v2: default embedder flipped from DeterministicHashEmbedder
#              to the real OllamaEmbedder (per radical option ratified
#              2026-04-24 — platform is multi-LLM and we test the real
#              adapter that production uses). Tests that genuinely need
#              deterministic vectors opt in via `c7_deterministic_embedder`.
#              Model: all-minilm (384-dim); pulled once at session start
#              by the `ollama_container` fixture.
# =============================================================================

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from minio import Minio

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.base import EmbeddingProvider
from ay_platform_core.c7_memory.embedding.deterministic import DeterministicHashEmbedder
from ay_platform_core.c7_memory.embedding.ollama import OllamaEmbedder
from ay_platform_core.c7_memory.router import router
from ay_platform_core.c7_memory.service import MemoryService
from ay_platform_core.c7_memory.service import get_service as c7_get_service
from ay_platform_core.c7_memory.storage.minio_storage import MemorySourceStorage
from tests.fixtures.containers import (
    ArangoEndpoint,
    MinioEndpoint,
    OllamaEndpoint,
    cleanup_arango_database,
    cleanup_minio_bucket,
)


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


@pytest_asyncio.fixture(scope="function")
async def c7_embedder(
    ollama_container: OllamaEndpoint,
) -> AsyncIterator[EmbeddingProvider]:
    """Default embedder for C7 integration tests: real Ollama (all-minilm).

    The dimension is probed on first call and cached on the embedder
    instance. Tests that need deterministic vectors instead SHALL depend
    on `c7_deterministic_embedder` (opt-in).
    """
    embedder = OllamaEmbedder(
        base_url=ollama_container.base_url,
        model_id=ollama_container.embed_model_id,
    )
    # Probe dimension so downstream fixtures can read embedder.dimension.
    await embedder.embed_one("fixture-warmup")
    try:
        yield embedder
    finally:
        await embedder.aclose()


@pytest.fixture(scope="function")
def c7_deterministic_embedder() -> DeterministicHashEmbedder:
    """Opt-in reproducible embedder for tests that assert on specific
    vector properties. Kept for regression coverage of the hash-based
    baseline."""
    return DeterministicHashEmbedder(dimension=64)


@pytest_asyncio.fixture(scope="function")
async def c7_config(c7_embedder: EmbeddingProvider) -> MemoryConfig:
    """Config aligned with the real embedder's dimension. `c7_embedder`
    has already probed Ollama, so `embedder.dimension` is accurate."""
    return MemoryConfig(
        embedding_adapter="ollama",
        embedding_model_id=c7_embedder.model_id,
        embedding_dimension=c7_embedder.dimension,
        chunk_token_size=20,
        chunk_overlap=4,
        default_quota_bytes=1024 * 1024,
        retrieval_scan_cap=1000,
    )


@pytest.fixture(scope="function")
def c7_service(
    c7_config: MemoryConfig,
    c7_repo: MemoryRepository,
    c7_embedder: EmbeddingProvider,
) -> MemoryService:
    return MemoryService(config=c7_config, repo=c7_repo, embedder=c7_embedder)


@pytest.fixture(scope="function")
def c7_app(c7_service: MemoryService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.memory_service = c7_service
    return app


# ---------------------------------------------------------------------------
# Phase B fixtures — MinIO blob storage for the upload pipeline.
# Uses a deterministic embedder for speed; embedder choice is irrelevant
# to upload-path tests which focus on parser + blob + chunk persistence.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def c7_storage(
    minio_container: MinioEndpoint,
) -> Iterator[MemorySourceStorage]:
    bucket = f"c7-upload-test-{uuid.uuid4().hex[:6]}"
    client = Minio(
        minio_container.endpoint,
        access_key=minio_container.access_key,
        secret_key=minio_container.secret_key,
        secure=False,
    )
    storage = MemorySourceStorage(client, bucket)
    storage._ensure_bucket_sync()
    try:
        yield storage
    finally:
        cleanup_minio_bucket(minio_container, bucket)


@pytest.fixture(scope="function")
def c7_upload_service(
    c7_repo: MemoryRepository,
    c7_deterministic_embedder: DeterministicHashEmbedder,
    c7_storage: MemorySourceStorage,
) -> MemoryService:
    """Service wired for upload-pipeline tests: real Arango + real MinIO,
    deterministic embedder for speed."""
    return MemoryService(
        config=MemoryConfig(
            embedding_adapter="deterministic-hash",
            embedding_model_id="deterministic-hash-v1",
            embedding_dimension=c7_deterministic_embedder.dimension,
            chunk_token_size=64,
            chunk_overlap=8,
            default_quota_bytes=1024 * 1024 * 1024,
            retrieval_scan_cap=1000,
        ),
        repo=c7_repo,
        embedder=c7_deterministic_embedder,
        storage=c7_storage,
    )


@pytest.fixture(scope="function")
def c7_upload_app(c7_upload_service: MemoryService) -> FastAPI:
    """FastAPI app with c7 router + upload-ready service."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[c7_get_service] = lambda: c7_upload_service
    return app
