# =============================================================================
# File: main.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c7_memory/main.py
# Description: FastAPI app factory for C7 Memory Service. v2 adds adapter
#              selection based on C7_EMBEDDING_ADAPTER
#              ("deterministic-hash" default; "ollama" for real embeddings
#              against an Ollama-compatible server).
#
# @relation implements:R-100-114
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.base import EmbeddingProvider
from ay_platform_core.c7_memory.embedding.deterministic import DeterministicHashEmbedder
from ay_platform_core.c7_memory.embedding.ollama import OllamaEmbedder
from ay_platform_core.c7_memory.router import router
from ay_platform_core.c7_memory.service import MemoryService


def _build_embedder(cfg: MemoryConfig) -> EmbeddingProvider:
    """Select the embedding adapter declared by ``C7_EMBEDDING_ADAPTER``.

    Adding a new adapter means adding a new value here + a corresponding
    import above. Unknown values fail fast at startup rather than silently
    falling back.
    """
    name = cfg.embedding_adapter
    if name == "deterministic-hash":
        return DeterministicHashEmbedder(
            model_id=cfg.embedding_model_id, dimension=cfg.embedding_dimension
        )
    if name == "ollama":
        return OllamaEmbedder(
            base_url=cfg.embedding_ollama_url,
            model_id=cfg.embedding_model_id,
            request_timeout_s=cfg.embedding_ollama_timeout_s,
        )
    raise ValueError(
        f"unknown C7 embedding adapter {name!r}. "
        f"Accepted: 'deterministic-hash', 'ollama'."
    )


def create_app(config: MemoryConfig | None = None) -> FastAPI:
    cfg = config or MemoryConfig()
    arango_client = ArangoClient(hosts=f"http://{cfg.arango_host}:{cfg.arango_port}")
    db = arango_client.db(
        cfg.arango_db, username=cfg.arango_user, password=cfg.arango_password
    )
    repo = MemoryRepository(db)
    embedder = _build_embedder(cfg)
    service = MemoryService(config=cfg, repo=repo, embedder=embedder)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo._ensure_collections_sync()
        yield
        # The Ollama adapter owns its httpx client; close it cleanly on
        # shutdown. Other adapters are no-op.
        aclose = getattr(embedder, "aclose", None)
        if aclose is not None:
            await aclose()

    app = FastAPI(title="C7 Memory Service", lifespan=lifespan)
    app.include_router(router)
    app.state.memory_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c7_memory"}

    return app


app = create_app()
