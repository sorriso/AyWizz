# =============================================================================
# File: config.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c8_llm/config.py
# Description: Pydantic schema for `litellm-config.yaml` (R-800-020, R-800-024).
#              Two jobs: (1) strict validation of the structure LiteLLM
#              consumes at deploy time; (2) canonical in-Python
#              representation that the agent/feature validator reads.
#              Client-side settings (gateway URL, timeouts) live in the
#              ClientSettings class also defined here.
#
# @relation implements:R-800-020
# @relation implements:R-800-024
# =============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ay_platform_core.c8_llm.catalog import Feature

# ---------------------------------------------------------------------------
# LiteLLM config (YAML mounted as a ConfigMap in K8s)
# ---------------------------------------------------------------------------


class LiteLLMParams(BaseModel):
    """Fields under `model_list[*].litellm_params:` in `litellm-config.yaml`.

    Mirrors LiteLLM's native schema but we only validate the fields the
    platform cares about. `api_key:` is read from an env var reference
    (`os.environ/ANTHROPIC_API_KEY` etc.) per R-800-021.
    """

    model_config = ConfigDict(extra="allow")

    model: str  # provider/model identifier, e.g. "anthropic/claude-opus-4-7"
    api_key: str | None = None
    api_base: str | None = None


class ModelInfo(BaseModel):
    """Metadata attached to each model entry (R-800-024). Strictly typed
    because the router and cost tracker depend on these fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    features: list[Feature]
    context_window: int = Field(ge=1)
    cost_per_million_input: float = Field(ge=0.0)
    cost_per_million_output: float = Field(ge=0.0)
    cost_per_million_cached: float | None = Field(default=None, ge=0.0)
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    rate_limit_tpm: int | None = Field(default=None, ge=1)


class ModelEntry(BaseModel):
    """One entry of `model_list:` — a named model the router can resolve to."""

    model_config = ConfigDict(extra="forbid")

    model_name: str
    litellm_params: LiteLLMParams
    model_info: ModelInfo


class BudgetConfig(BaseModel):
    """Top-level `budgets:` section (R-800-061)."""

    model_config = ConfigDict(extra="forbid")

    default_hard_cap_usd_per_month: float = Field(default=100.0, ge=0.0)
    default_soft_cap_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    window: Literal["calendar_month_utc", "rolling_30_days"] = "calendar_month_utc"


class ArchivalConfig(BaseModel):
    """Top-level `archival:` section (R-800-090/091/092)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    minio_bucket: str = "llm-archive"
    encryption: Literal["sse-kms", "sse-c", "none"] = "none"


class RateLimitsConfig(BaseModel):
    """Top-level `rate_limits:` section (R-800-060)."""

    model_config = ConfigDict(extra="forbid")

    per_tenant_rpm: int | None = Field(default=None, ge=1)
    per_user_rpm: int | None = Field(default=None, ge=1)


class LiteLLMConfig(BaseModel):
    """Full root of `litellm-config.yaml`.

    Unknown top-level keys are forbidden so that typos in operational files
    are caught at validation time rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    model_list: list[ModelEntry]
    # Agent routes: name → model_name. Validated against the feature
    # catalog by `validator.validate_agent_routes`.
    agent_routes: dict[str, str] = Field(default_factory=dict)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    archival: ArchivalConfig = Field(default_factory=ArchivalConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)


# ---------------------------------------------------------------------------
# Client-side settings (consumed by LLMGatewayClient)
# ---------------------------------------------------------------------------


class ClientSettings(BaseSettings):
    """Runtime configuration for the gateway client.

    Pydantic-settings reads from the environment (prefixed `C8_`) so that
    K8s deployments can inject the proxy address and default tenant
    without code changes.
    """

    model_config = SettingsConfigDict(env_prefix="c8_", extra="ignore")

    # ClusterIP service URL per R-800-001. Default assumes docker-compose
    # local dev where the proxy is reachable at http://c8:8000/v1.
    gateway_url: str = "http://c8:8000/v1"
    request_timeout_seconds: float = Field(default=60.0, ge=1.0)
    connect_timeout_seconds: float = Field(default=5.0, ge=0.1)
    # Streaming heartbeat interval (Q-800-003 baseline: 15 s).
    sse_heartbeat_seconds: float = Field(default=15.0, ge=1.0)
