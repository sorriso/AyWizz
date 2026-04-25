# =============================================================================
# File: config.py
# Version: 3
# Path: ay_platform_core/src/ay_platform_core/c2_auth/config.py
# Description: Configuration for C2 Auth Service.
#
#              v3: env-var single-source refactor (R-100-110 v2, R-100-111 v2).
#              Facts that are platform-wide identical (Arango URL, DB name,
#              shared application credentials, OS-level switches) are now
#              read from UNPREFIXED env vars via `validation_alias`. Only
#              fields that legitimately differ between components keep the
#              `C2_` prefix (auth mode, JWT keys, token TTL).
#
#              v2: harmonised env-var naming under the C2_ prefix.
#              v1: initial.
#
# @relation implements:R-100-111
# @relation implements:R-100-112
# @relation implements:R-100-110
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseSettings):
    """Settings for C2 Auth Service, loaded from environment.

    Priority: init kwargs > env vars > defaults.
    Per-component fields use the ``C2_`` prefix; shared fields use
    ``validation_alias`` to read unprefixed names.
    """

    # populate_by_name=True so model_validate(...) accepts field names
    # alongside the validation_alias for shared knobs.
    model_config = SettingsConfigDict(
        env_prefix="c2_", extra="ignore", populate_by_name=True
    )

    # ---- Platform-wide (read without prefix via validation_alias) -----------
    platform_environment: Literal["development", "testing", "staging", "production"] = (
        Field(default="development", validation_alias="PLATFORM_ENVIRONMENT")
    )

    # Shared ArangoDB connection — every component talks to the same cluster
    # and the same logical database; ownership boundaries are enforced at the
    # collection level (R-100-012 v3) and via the dedicated app user.
    arango_url: str = Field(
        default="http://arangodb:8529", validation_alias="ARANGO_URL"
    )
    arango_db: str = Field(default="platform", validation_alias="ARANGO_DB")
    arango_username: str = Field(default="ay_app", validation_alias="ARANGO_USERNAME")
    arango_password: str = Field(
        default="changeme", validation_alias="ARANGO_PASSWORD"
    )

    # ---- C2-specific (C2_ prefix) ------------------------------------------
    auth_mode: Literal["none", "local", "sso"] = Field(
        default="none",
        description="Pluggable auth mode. R-100-030.",
    )

    jwt_algorithm: Literal["HS256", "RS256", "EdDSA"] = Field(
        default="HS256",
        description="Signing algorithm. HS256 for dev, RS256/EdDSA for prod. R-100-038.",
    )
    jwt_secret_key: str = Field(
        default="change-me-in-production-min-32-chars!!",
        description="Symmetric key for HS256. Must be >=32 chars.",
    )
    jwt_private_key: str = Field(
        default="",
        description="PEM-encoded private key for RS256/EdDSA signing.",
    )
    jwt_public_key: str = Field(
        default="",
        description="PEM-encoded public key for RS256/EdDSA verification.",
    )
    token_ttl_seconds: int = Field(
        default=3600,
        description="Token lifetime in seconds. Default 1h per E-100-001.",
    )

    # Pre-existing admin user bootstrapped by the C2 lifespan when
    # `auth_mode == "local"`. Ignored in `none` / `sso` modes — but the
    # values are still declared here so the env file stays exhaustive
    # (R-100-110 v2). R-100-118 v2.
    local_admin_username: str = Field(
        default="admin",
        description="Username of the bootstrap admin (auth_mode=local).",
    )
    local_admin_password: str = Field(
        default="changeme",
        description="Password of the bootstrap admin (auth_mode=local).",
    )
