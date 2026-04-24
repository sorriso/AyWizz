# =============================================================================
# File: config.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c2_auth/config.py
# Description: Configuration for C2 Auth Service. All values read from
#              environment variables; defaults target local development.
#              v2: harmonised env-var naming — every field is now read via
#              the `C2_` prefix (was `AUTH_*` / `ARANGO_*` in v1). The
#              only exception is `PLATFORM_ENVIRONMENT`, which is
#              cross-cutting platform-wide and declared via
#              `validation_alias` so all components share one variable.
#
# @relation implements:R-100-111
# @relation implements:R-100-112
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseSettings):
    """Settings for C2 Auth Service, loaded from environment.

    Priority: init kwargs > env vars > defaults.
    Env-var names are ``C2_<FIELD>`` (case-insensitive, upper-cased on disk).
    """

    # populate_by_name=True so `AuthConfig.model_validate({"platform_environment": ...})`
    # continues to work alongside the PLATFORM_ENVIRONMENT validation_alias.
    model_config = SettingsConfigDict(
        env_prefix="c2_", extra="ignore", populate_by_name=True
    )

    # ---- Auth mode ----------------------------------------------------------
    auth_mode: Literal["none", "local", "sso"] = Field(
        default="none",
        description="Pluggable auth mode. R-100-030.",
    )

    # ---- JWT signing --------------------------------------------------------
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

    # ---- Platform-wide guard ------------------------------------------------
    # Read from `PLATFORM_ENVIRONMENT` (no prefix) so every component shares
    # a single variable in the env file. `validation_alias` overrides the
    # env_prefix rule for this specific field.
    platform_environment: Literal["development", "testing", "staging", "production"] = Field(
        default="development",
        validation_alias="PLATFORM_ENVIRONMENT",
        description="Deployment environment. 'none' mode forbidden in prod/staging. R-100-032.",
    )

    # ---- ArangoDB (local mode) ----------------------------------------------
    arango_url: str = Field(default="http://localhost:8529")
    arango_db_name: str = Field(default="platform")
    arango_username: str = Field(default="root")
    arango_password: str = Field(default="")
