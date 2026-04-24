# =============================================================================
# File: config.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/config.py
# Description: Runtime settings for the C4 Orchestrator. Reads from env
#              vars prefixed `C4_`.
#
# @relation implements:R-100-111
# =============================================================================

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorConfig(BaseSettings):
    """C4 runtime settings."""

    model_config = SettingsConfigDict(env_prefix="c4_", extra="ignore")

    # ArangoDB (for c4_runs per E-200-001)
    arango_host: str = "arangodb"
    arango_port: int = 8529
    arango_db: str = "platform"
    arango_user: str = "root"
    arango_password: str = "password"

    # MinIO (dispatch bundles under c4-dispatch/ per R-200-033)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
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
