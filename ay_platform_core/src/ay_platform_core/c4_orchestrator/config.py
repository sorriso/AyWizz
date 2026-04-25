# =============================================================================
# File: config.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/config.py
# Description: Runtime settings for the C4 Orchestrator.
#
#              v2: env-var single-source refactor (R-100-110 v2, R-100-111
#              v2). Shared infra params (Arango, MinIO endpoint + creds,
#              platform environment) are read from UNPREFIXED env vars via
#              validation_alias. Only fields that legitimately differ
#              between components keep the `C4_` prefix (caps, timeouts,
#              dispatcher backend, MinIO bucket).
#
# @relation implements:R-100-111
# @relation implements:R-100-110
# @relation implements:R-100-112
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorConfig(BaseSettings):
    """C4 runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="c4_", extra="ignore", populate_by_name=True
    )

    # ---- Platform-wide (read without prefix via validation_alias) -----------
    platform_environment: Literal["development", "testing", "staging", "production"] = (
        Field(default="development", validation_alias="PLATFORM_ENVIRONMENT")
    )

    # Shared ArangoDB connection
    arango_url: str = Field(
        default="http://arangodb:8529", validation_alias="ARANGO_URL"
    )
    arango_db: str = Field(default="platform", validation_alias="ARANGO_DB")
    arango_username: str = Field(default="ay_app", validation_alias="ARANGO_USERNAME")
    arango_password: str = Field(
        default="changeme", validation_alias="ARANGO_PASSWORD"
    )

    # Shared MinIO connection
    minio_endpoint: str = Field(default="minio:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="ay_app", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(
        default="changeme", validation_alias="MINIO_SECRET_KEY"
    )
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")

    # ---- C4-specific (C4_ prefix) ------------------------------------------
    # Each component owns its own bucket; the bucket name DOES legitimately
    # differ across components, so it stays prefixed.
    minio_bucket: str = "orchestrator"

    # Context enrichment cap (R-200-040)
    enrichment_round_cap: int = Field(default=3, ge=0)
    # Three-fix rule threshold (R-200-051)
    fix_attempt_cap: int = Field(default=3, ge=1)
    # Sub-agent pod hard timeout (R-200-032). In the in-process
    # dispatcher this bounds the LLM call + post-processing duration.
    sub_agent_timeout_seconds: int = Field(default=900, ge=30)

    # Whether to use the real K8s pod dispatcher (future). Baseline v1:
    # in-process dispatcher without real pods (Q-200-001 / R-200-030
    # reserve the real dispatcher for infra-ready deployments).
    dispatcher_backend: str = Field(default="in-process")
