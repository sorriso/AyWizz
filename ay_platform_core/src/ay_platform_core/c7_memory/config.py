# =============================================================================
# File: config.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c7_memory/config.py
# Description: Runtime settings for C7. Read from env vars prefixed `C7_`.
#
# @relation implements:R-100-111
# =============================================================================

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryConfig(BaseSettings):
    """C7 runtime configuration."""

    model_config = SettingsConfigDict(env_prefix="c7_", extra="ignore")

    # ArangoDB (memory_chunks, memory_sources, memory_links)
    arango_host: str = "arangodb"
    arango_port: int = 8529
    arango_db: str = "platform"
    arango_user: str = "root"
    arango_password: str = "password"

    # MinIO (raw source files + parsed/chunks artefacts)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "memory"

    # Embedding adapter selection.
    #   - "deterministic-hash": zero-dep baseline (reproducible, no ML).
    #   - "ollama": call a running Ollama server at `embedding_ollama_url`
    #     serving `embedding_model_id` (e.g. "all-minilm"). Dimension is
    #     discovered at first call.
    embedding_adapter: str = "deterministic-hash"
    embedding_model_id: str = "deterministic-hash-v1"
    embedding_dimension: int = Field(default=128, ge=8)
    embedding_ollama_url: str = "http://ollama:11434"
    embedding_ollama_timeout_s: float = Field(default=30.0, ge=1.0)

    # Chunking (R-400-022)
    chunk_token_size: int = Field(default=512, ge=16)
    chunk_overlap: int = Field(default=64, ge=0)

    # Per-project storage quota (R-400-024). Default 1 GB.
    default_quota_bytes: int = Field(default=1 * 1024 * 1024 * 1024, ge=0)

    # Retrieval scan cap (R-400-011). Queries that would scan more than
    # this many rows SHALL be filtered down first.
    retrieval_scan_cap: int = Field(default=50_000, ge=100)
