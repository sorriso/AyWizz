# =============================================================================
# File: config.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c7_memory/config.py
# Description: Runtime settings for C7 Memory Service.
#
#              v2: env-var single-source refactor (R-100-110 v2, R-100-111
#              v2). Shared infra params read via validation_alias, including
#              the new platform-wide `OLLAMA_URL` (was C7-specific
#              `C7_EMBEDDING_OLLAMA_URL`). Per-component fields keep the
#              `C7_` prefix.
#
# @relation implements:R-100-111
# @relation implements:R-100-110
# @relation implements:R-100-112
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryConfig(BaseSettings):
    """C7 runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="c7_", extra="ignore", populate_by_name=True
    )

    # ---- Platform-wide (read without prefix via validation_alias) -----------
    platform_environment: Literal["development", "testing", "staging", "production"] = (
        Field(default="development", validation_alias="PLATFORM_ENVIRONMENT")
    )

    # Shared ArangoDB
    arango_url: str = Field(
        default="http://arangodb:8529", validation_alias="ARANGO_URL"
    )
    arango_db: str = Field(default="platform", validation_alias="ARANGO_DB")
    arango_username: str = Field(default="ay_app", validation_alias="ARANGO_USERNAME")
    arango_password: str = Field(
        default="changeme", validation_alias="ARANGO_PASSWORD"
    )

    # Shared MinIO
    minio_endpoint: str = Field(default="minio:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="ay_app", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(
        default="changeme", validation_alias="MINIO_SECRET_KEY"
    )
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")

    # Shared Ollama (C7 is the only consumer today, but the URL is platform-
    # level; promoted to a shared knob so a future component reusing Ollama
    # picks up the same value with no duplication.)
    ollama_url: str = Field(
        default="http://ollama:11434", validation_alias="OLLAMA_URL"
    )

    # ---- C7-specific (C7_ prefix) ------------------------------------------
    minio_bucket: str = "memory"

    # Embedding adapter selection.
    #   - "deterministic-hash": zero-dep baseline (reproducible, no ML).
    #   - "ollama": call the running Ollama server at the shared `OLLAMA_URL`
    #     serving `embedding_model_id` (e.g. "all-minilm").
    embedding_adapter: str = "deterministic-hash"
    embedding_model_id: str = "deterministic-hash-v1"
    embedding_dimension: int = Field(default=128, ge=8)
    # The Ollama call timeout is C7-specific (it is THIS component that calls
    # Ollama; another component might tolerate a different latency budget).
    embedding_ollama_timeout_s: float = Field(default=30.0, ge=1.0)

    # Chunking (R-400-022)
    chunk_token_size: int = Field(default=512, ge=16)
    chunk_overlap: int = Field(default=64, ge=0)

    # Per-project storage quota (R-400-024). Default 1 GB.
    default_quota_bytes: int = Field(default=1 * 1024 * 1024 * 1024, ge=0)

    # Retrieval scan cap (R-400-011). Queries that would scan more than
    # this many rows SHALL be filtered down first.
    retrieval_scan_cap: int = Field(default=50_000, ge=100)
