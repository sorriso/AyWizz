# =============================================================================
# File: config.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c5_requirements/config.py
# Description: Runtime configuration for the C5 Requirements Service.
#              Reads from env vars via pydantic-settings so that K8s
#              deployments can inject MinIO and ArangoDB connection
#              parameters without code changes.
#
# @relation implements:R-100-111
# @relation implements:R-100-112
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RequirementsConfig(BaseSettings):
    """C5 runtime settings.

    Environment variables are prefixed with `C5_` to avoid collision with
    sibling components. MinIO and ArangoDB creds SHALL be provided as
    secrets in production.
    """

    # populate_by_name=True so code passing field names via model_validate
    # keeps working alongside PLATFORM_ENVIRONMENT's validation_alias.
    model_config = SettingsConfigDict(
        env_prefix="c5_", extra="ignore", populate_by_name=True
    )

    # MinIO (source of truth per R-300-010)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    # Bucket naming follows R-300-010: projects/<pid>/requirements/ and
    # platform/requirements/. The bucket itself is a single shared bucket;
    # paths are scoped inside it.
    minio_bucket: str = "requirements"

    # ArangoDB (derived index per R-300-012)
    arango_host: str = "arangodb"
    arango_port: int = 8529
    arango_db: str = "platform"
    arango_user: str = "root"
    arango_password: str = "password"

    # Idempotency cache (R-300-021): 24 h default
    idempotency_ttl_seconds: int = 86400

    # Reconciliation worker (R-300-063): 15-minute default cadence
    reconcile_interval_seconds: int = 900

    # Environment gate for destructive operations (reindex, etc.).
    # Read from `PLATFORM_ENVIRONMENT` (no prefix) — cross-cutting variable
    # shared by every component's config via validation_alias, so a single
    # line in the env file propagates to the whole platform.
    platform_environment: Literal["development", "testing", "staging", "production"] = (
        Field(default="development", validation_alias="PLATFORM_ENVIRONMENT")
    )
