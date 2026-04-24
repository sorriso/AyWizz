# =============================================================================
# File: models.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c6_validation/models.py
# Description: Pydantic v2 models for C6 — public contracts (Finding,
#              ValidationRun, CheckSpec, PluginDescriptor) and internal
#              structures (RelationMarker, CodeArtifact, CheckContext,
#              CheckResult) used by plugins.
#
# @relation implements:R-700-001
# @relation implements:E-700-001
# @relation implements:E-700-002
# =============================================================================

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    """Finding severity. `blocking` fails the run gate; others are advisory."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"
    INFO = "info"


class FindingStatus(StrEnum):
    """Lifecycle of a finding — v1 only emits `open`; lifecycle moves come v2."""

    OPEN = "open"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class RunStatus(StrEnum):
    """Lifecycle of a validation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RelationVerb(StrEnum):
    """Closed set of verbs accepted by the v1 marker parser (R-700-040)."""

    IMPLEMENTS = "implements"
    VALIDATES = "validates"
    USES = "uses"
    DERIVES_FROM = "derives-from"


# ---------------------------------------------------------------------------
# Internal structures used by plugins (defined first: referenced in requests)
# ---------------------------------------------------------------------------


class CodeArtifact(BaseModel):
    """A single code-domain artifact available for inspection during a run.

    v1: passed directly into the run by the orchestrator or a test. v2 will
    fetch artifacts from C10 (MinIO) via the artifact store adapter.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    is_test: bool = False


class RelationMarker(BaseModel):
    """One parsed `@relation <verb>:<target>` marker found in an artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_path: str
    line: int
    verb: RelationVerb
    targets: list[str]


# ---------------------------------------------------------------------------
# Public contracts
# ---------------------------------------------------------------------------


class CheckSpec(BaseModel):
    """Declaration of one check registered by a plugin."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    title: str
    severity_default: Severity
    description: str


class PluginDescriptor(BaseModel):
    """Plugin registration metadata. Exposed via GET /validation/plugins."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    name: str
    version: str
    artifact_formats: list[str]
    checks: list[CheckSpec]


class Finding(BaseModel):
    """E-700-001 projection — single validation result row."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    run_id: str
    check_id: str
    domain: str
    severity: Severity
    status: FindingStatus = FindingStatus.OPEN
    artifact_ref: str | None = None
    location: str | None = None
    entity_id: str | None = None
    message: str
    fix_hint: str | None = None
    created_at: datetime


class RunSummaryCounts(BaseModel):
    """Aggregated counts by severity."""

    model_config = ConfigDict(extra="forbid")

    blocking: int = 0
    advisory: int = 0
    info: int = 0


class ValidationRun(BaseModel):
    """E-700-002 projection — run metadata + aggregate result."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str
    domain: str
    check_ids: list[str] = Field(default_factory=list)
    status: RunStatus
    findings_count: RunSummaryCounts = Field(default_factory=RunSummaryCounts)
    started_at: datetime
    completed_at: datetime | None = None
    snapshot_uri: str | None = None


class RunTriggerRequest(BaseModel):
    """POST /validation/runs body.

    v1: the caller passes the corpus (``requirements``) and the code artifacts
    (``artifacts``) directly. v2 will fetch these from C5 + C10 when the
    orchestrator integration is wired. Keeping them here makes the endpoint
    self-contained for integration testing and for MCP (C9) consumption.
    """

    model_config = ConfigDict(extra="forbid")

    domain: str
    project_id: str
    check_ids: list[str] = Field(default_factory=list)
    requirements: list[dict[str, object]] = Field(default_factory=list)
    artifacts: list[CodeArtifact] = Field(default_factory=list)


class RunTriggerResponse(BaseModel):
    """POST /validation/runs response (HTTP 202)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus


class FindingPage(BaseModel):
    """Paginated findings listing."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    total: int
    items: list[Finding]


class DomainList(BaseModel):
    """Response wrapper for GET /validation/domains.

    Wrapped (rather than ``list[str]``) so the response passes the
    monorepo's router-typing coherence check: every REST response model
    must be a Pydantic ``BaseModel`` (coherence test, scripts/checks/
    check_router_typing).
    """

    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal runtime context / result (consumed by plugins; not REST-exposed)
# ---------------------------------------------------------------------------


class CheckContext(BaseModel):
    """Inputs available to a plugin's `run_check()`."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    project_id: str
    domain: str
    requirements: list[dict[str, object]] = Field(default_factory=list)
    artifacts: list[CodeArtifact] = Field(default_factory=list)
    markers: list[RelationMarker] = Field(default_factory=list)


class CheckResult(BaseModel):
    """Output of a plugin's `run_check()`."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    # ``error_message`` is populated iff the check raised; the service
    # translates this into a ``severity=info`` finding of
    # ``check_id=<check>:error``.
    error_message: str | None = None
