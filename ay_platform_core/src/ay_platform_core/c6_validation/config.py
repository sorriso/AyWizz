# =============================================================================
# File: config.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c6_validation/config.py
# Description: Runtime settings for C6. Env prefix `C6_`.
#
# @relation implements:R-700-050
# =============================================================================

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ValidationConfig(BaseSettings):
    """C6 runtime configuration."""

    model_config = SettingsConfigDict(env_prefix="c6_", extra="ignore")

    # ArangoDB (c6_runs, c6_findings)
    arango_host: str = "arangodb"
    arango_port: int = 8529
    arango_db: str = "platform"
    arango_user: str = "root"
    arango_password: str = "password"

    # MinIO (validation-reports/<project>/<run>.json)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "validation"

    # Per-check disable flags. Consumed by the service before dispatching a
    # check. Name pattern: a disabled check id `req-without-code` maps to
    # `C6_CHECK_REQ_WITHOUT_CODE_ENABLED=false`.
    #
    # We don't declare each flag individually; the service performs a dynamic
    # lookup via `os.environ.get`. The field below is a default for the
    # fallback path.
    default_check_enabled: bool = Field(default=True)

    # Cap on the number of findings written per run. Protects the DB when a
    # pathological run emits thousands of findings. Additional findings are
    # truncated with a single `severity=info` finding of
    # `check_id="<plugin>:truncated"`.
    max_findings_per_run: int = Field(default=5_000, ge=10)
