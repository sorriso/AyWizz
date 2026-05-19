# =============================================================================
# File: service.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/service.py
# Description: Facade for the C4 Orchestrator. Drives pipeline runs through
#              the five phases, honours the three hard gates, applies the
#              three-fix rule, and emits NATS events for hybrid exposure
#              (D-008). Consumes the AgentDispatcher protocol and a
#              DomainPlugin to stay domain-agnostic (D-012).
#
#              v2: on first successful generate-phase completion, the
#              orchestrator materialises the agent's `output.files` into
#              the artifacts surface (R-200-150..152), reusing the
#              orchestrator run_id as the artifact run_id. Materialisation
#              is best-effort : failures log a WARNING but never block the
#              pipeline (MinIO + Gitea are mirrors, not the source of
#              truth for state machine progression).
#
# @relation implements:R-200-001
# @relation implements:R-200-002
# @relation implements:R-200-003
# @relation implements:R-200-010
# @relation implements:R-200-011
# @relation implements:R-200-012
# @relation implements:R-200-040
# @relation implements:R-200-041
# @relation implements:R-200-050
# @relation implements:R-200-051
# @relation implements:R-200-052
# @relation implements:R-200-070
# @relation implements:R-200-150
# @relation implements:R-200-151
# @relation implements:R-200-152
# =============================================================================

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status

from ay_platform_core.c4_orchestrator.artifacts_models import ArtifactRunStatus
from ay_platform_core.c4_orchestrator.artifacts_service import ArtifactsService
from ay_platform_core.c4_orchestrator.config import OrchestratorConfig
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository
from ay_platform_core.c4_orchestrator.dispatcher.base import (
    AgentDispatcher,
    DispatchRequest,
)
from ay_platform_core.c4_orchestrator.dispatcher.in_process import agent_for_phase
from ay_platform_core.c4_orchestrator.domains.base import DomainPlugin
from ay_platform_core.c4_orchestrator.events.base import OrchestratorEventPublisher
from ay_platform_core.c4_orchestrator.models import (
    AgentCompletion,
    AgentConcern,
    EscalationStatus,
    Gate,
    GateResult,
    Phase,
    RunCreate,
    RunFeedback,
    RunPublic,
    RunResume,
    RunResumeStrategy,
    RunStatus,
)
from ay_platform_core.c4_orchestrator.state import decide_transition

_log = logging.getLogger("c4_orchestrator.service")


class OrchestratorService:
    """Public API of C4. Methods map 1:1 to router endpoints (§6.1)."""

    def __init__(
        self,
        config: OrchestratorConfig,
        repo: OrchestratorRepository,
        dispatcher: AgentDispatcher,
        domain_plugin: DomainPlugin,
        publisher: OrchestratorEventPublisher,
        artifacts_service: ArtifactsService | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._dispatcher = dispatcher
        self._domain = domain_plugin
        self._publisher = publisher
        # Optional artifacts service — when wired, the orchestrator
        # materialises generate-phase `output.files` into the artifacts
        # surface on the first successful generate (R-200-151). None is
        # tolerated (legacy tests / standalone pipelines without MinIO).
        self._artifacts = artifacts_service

    # ------------------------------------------------------------------
    # Run creation
    # ------------------------------------------------------------------

    async def start_run(
        self,
        payload: RunCreate,
        *,
        tenant_id: str,
        user_id: str,
    ) -> RunPublic:
        """Create a run and execute the first phase (brainstorm)."""
        # R-200-002: reject if another run is still active for this session.
        active = await self._repo.find_active_by_session(
            payload.project_id, payload.session_id
        )
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"another run is active for this session: {active['_key']}"
                ),
            )

        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row: dict[str, Any] = {
            "_key": run_id,
            "run_id": run_id,
            "project_id": payload.project_id,
            "session_id": payload.session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "domain": payload.domain,
            "initial_prompt": payload.initial_prompt,
            "current_phase": Phase.BRAINSTORM.value,
            "status": RunStatus.RUNNING.value,
            "started_at": now.isoformat(),
            "completed_at": None,
            "concerns": [],
            "fix_attempts": {},
            "enrichment_rounds": {Phase.BRAINSTORM.value: 0},
            "events_emitted": 0,
            "minio_root": f"c4-runs/{run_id}/",
            "gate_a_approved": False,
        }
        await self._repo.upsert_run(row)
        await self._publish(
            run_id,
            "phase.started",
            {"phase": Phase.BRAINSTORM.value, "agent": "architect"},
        )

        # Execute the first phase inline so the caller sees progress
        # immediately. Subsequent phases advance via /feedback or
        # /resume, or autonomously after gate checks.
        await self._run_phase(row)
        return _public(row)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_run(self, run_id: str) -> RunPublic:
        row = await self._repo.get_run(run_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            )
        return _public(row)

    # ------------------------------------------------------------------
    # Interactive feedback (brainstorm / spec / plan)
    # ------------------------------------------------------------------

    async def handle_feedback(
        self, run_id: str, payload: RunFeedback
    ) -> RunPublic:
        row = await self._repo.get_run(run_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            )
        if row["status"] != RunStatus.RUNNING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"run is not running (status={row['status']})",
            )

        # Gate A: approval on the plan phase unlocks `generate` (R-200-010).
        if payload.phase == Phase.PLAN and payload.approved is True:
            row["gate_a_approved"] = True
            await self._repo.upsert_run(row)
            await self._publish(
                run_id, "gate.passed", {"gate": Gate.A_DESIGN_APPROVED.value}
            )
            # Advance to generate if the current phase is waiting on approval.
            if row["current_phase"] == Phase.PLAN.value:
                row["current_phase"] = Phase.GENERATE.value
                row["enrichment_rounds"][Phase.GENERATE.value] = 0
                await self._repo.upsert_run(row)
                await self._run_phase(row)
            return _public(row)

        # Otherwise the feedback is appended to the prompt and the
        # current phase is re-run. We treat the user-provided feedback
        # as an additional context round.
        if payload.user_feedback:
            row["initial_prompt"] = (
                f"{row['initial_prompt']}\n\n-- user feedback --\n"
                f"{payload.user_feedback}"
            )
            await self._repo.upsert_run(row)
            await self._run_phase(row)
        return _public(row)

    # ------------------------------------------------------------------
    # Admin resume after BLOCKED halt
    # ------------------------------------------------------------------

    async def resume_run(self, run_id: str, payload: RunResume) -> RunPublic:
        row = await self._repo.get_run(run_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            )
        if row["status"] != RunStatus.BLOCKED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"run is not blocked (status={row['status']})",
            )

        if payload.strategy == RunResumeStrategy.ABORT:
            row["status"] = RunStatus.COMPLETED.value
            row["completed_at"] = datetime.now(UTC).isoformat()
            await self._repo.upsert_run(row)
            await self._publish(
                run_id, "run.completed", {"reason": "aborted by admin"}
            )
            return _public(row)

        if payload.strategy == RunResumeStrategy.RETRY:
            # Reset enrichment counter for the current phase; keep fix_attempts.
            row["status"] = RunStatus.RUNNING.value
            row["enrichment_rounds"][row["current_phase"]] = 0
            await self._repo.upsert_run(row)
            await self._run_phase(row)
            return _public(row)

        # strategy == SKIP_PHASE — Q-200-009 defers semantics to v2.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "resume strategy 'skip-phase' deferred to C4 v2 (Q-200-009)"
            ),
        )

    # ------------------------------------------------------------------
    # Phase execution core
    # ------------------------------------------------------------------

    async def _run_phase(self, row: dict[str, Any]) -> None:
        """Dispatch the current phase and advance per the state machine.

        Loops autonomously through non-interactive phases until it hits
        a phase that awaits user input (plan — Gate A), a terminal state
        (completed/blocked), or the enrichment cap.
        """
        while row["status"] == RunStatus.RUNNING.value:
            current_phase = Phase(row["current_phase"])

            # Plan phase halts awaiting Gate A approval.
            if current_phase == Phase.PLAN and not row.get("gate_a_approved"):
                # Execute the plan phase once then wait for feedback.
                completion = await self._invoke_agent(row, current_phase)
                await self._apply_completion(row, current_phase, completion)
                # After planner completion the run stays in PLAN until the
                # user sends feedback with approved=True. Don't auto-advance.
                return

            completion = await self._invoke_agent(row, current_phase)
            await self._apply_completion(row, current_phase, completion)
            if row["status"] != RunStatus.RUNNING.value:
                return

            # Gate evaluations on phase boundaries
            if current_phase == Phase.GENERATE and completion.status in (
                EscalationStatus.DONE,
                EscalationStatus.DONE_WITH_CONCERNS,
            ):
                proceed = await self._handle_generate_gate_b(row, completion)
                if not proceed:
                    if row["status"] != RunStatus.RUNNING.value:
                        return
                    continue  # retry after fix attempt

            if current_phase == Phase.REVIEW and completion.status in (
                EscalationStatus.DONE,
                EscalationStatus.DONE_WITH_CONCERNS,
            ):
                gate_c = await self._domain.evaluate_gate_c(
                    row["run_id"], dict(completion.output)
                )
                if not gate_c.passed:
                    await self._handle_gate_failure(row, current_phase, gate_c)
                    if row["status"] != RunStatus.RUNNING.value:
                        return
                    continue
                await self._publish(
                    row["run_id"],
                    "gate.passed",
                    {"gate": gate_c.gate.value, "artifact_id": gate_c.artifact_id},
                )

            # Decide the next state purely from the completion
            rounds_used = int(row["enrichment_rounds"].get(current_phase.value, 0))
            transition = decide_transition(
                current_phase,
                completion.status,
                enrichment_rounds_used=rounds_used,
                enrichment_round_cap=self._config.enrichment_round_cap,
            )
            if transition.run_completed:
                row["status"] = RunStatus.COMPLETED.value
                row["completed_at"] = datetime.now(UTC).isoformat()
                await self._repo.upsert_run(row)
                await self._publish(
                    row["run_id"], "run.completed", {"final_phase": current_phase.value}
                )
                return
            if transition.run_blocked:
                # Build an operator-readable reason. When the agent
                # completion already carries a `blocker.reason` (parse
                # failure, unknown status, model refusal, etc.) we
                # surface it verbatim ; otherwise we fall back to the
                # state-machine status which is at least diagnostic.
                detail = (
                    completion.blocker.reason
                    if completion.blocker is not None
                    else completion.status.value
                )
                await self._block_run(
                    row,
                    reason=f"phase {current_phase.value} blocked: {detail}",
                )
                return
            if transition.retry_phase:
                row["enrichment_rounds"][current_phase.value] = rounds_used + 1
                await self._repo.upsert_run(row)
                continue

            # Advance to next phase
            assert transition.next_phase is not None
            row["current_phase"] = transition.next_phase.value
            row["enrichment_rounds"].setdefault(transition.next_phase.value, 0)
            await self._repo.upsert_run(row)
            await self._publish(
                row["run_id"],
                "phase.completed",
                {"phase": current_phase.value, "status": completion.status.value},
            )
            await self._publish(
                row["run_id"],
                "phase.started",
                {
                    "phase": transition.next_phase.value,
                    "agent": agent_for_phase(transition.next_phase).value,
                },
            )

    async def _invoke_agent(
        self, row: dict[str, Any], phase: Phase
    ) -> AgentCompletion:
        dispatch = DispatchRequest(
            run_id=row["run_id"],
            phase=phase,
            agent=agent_for_phase(phase),
            session_id=row["session_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            prompt=row["initial_prompt"],
            context_bundle={
                "domain": row["domain"],
                "concerns_so_far": row.get("concerns", []),
            },
        )
        await self._publish(
            row["run_id"],
            "agent.invoked",
            {"phase": phase.value, "agent": dispatch.agent.value},
        )
        completion = await self._dispatcher.dispatch(dispatch)
        await self._publish(
            row["run_id"],
            "agent.completed",
            {
                "phase": phase.value,
                "agent": completion.agent.value,
                "status": completion.status.value,
            },
        )
        return completion

    async def _apply_completion(
        self,
        row: dict[str, Any],
        phase: Phase,
        completion: AgentCompletion,
    ) -> None:
        if completion.concerns:
            row["concerns"].extend([
                {"phase": phase.value, **c.model_dump()} for c in completion.concerns
            ])
        await self._repo.upsert_run(row)

    async def _handle_gate_failure(
        self, row: dict[str, Any], phase: Phase, gate: GateResult
    ) -> None:
        artifact_id = gate.artifact_id or "unknown"
        attempts_map: dict[str, int] = dict(row.get("fix_attempts", {}))
        attempts_map[artifact_id] = int(attempts_map.get(artifact_id, 0)) + 1
        row["fix_attempts"] = attempts_map
        await self._repo.upsert_run(row)
        await self._publish(
            row["run_id"],
            "gate.blocked",
            {
                "gate": gate.gate.value,
                "artifact_id": artifact_id,
                "reason": gate.reason,
                "fix_attempts": attempts_map[artifact_id],
            },
        )
        if attempts_map[artifact_id] >= self._config.fix_attempt_cap:
            await self._publish(
                row["run_id"],
                "review.requested",
                {
                    "artifact_id": artifact_id,
                    "fix_attempts": attempts_map[artifact_id],
                    "gate": gate.gate.value,
                },
            )
            await self._block_run(
                row,
                reason=(
                    f"three-fix rule triggered on {phase.value} / "
                    f"{gate.gate.value} for {artifact_id}"
                ),
            )

    async def _block_run(self, row: dict[str, Any], *, reason: str) -> None:
        row["status"] = RunStatus.BLOCKED.value
        row["completed_at"] = datetime.now(UTC).isoformat()
        row["block_reason"] = reason
        await self._repo.upsert_run(row)
        await self._publish(row["run_id"], "run.blocked", {"reason": reason})

    # ------------------------------------------------------------------
    # Generate-phase post-completion handler
    # ------------------------------------------------------------------

    async def _handle_generate_gate_b(
        self, row: dict[str, Any], completion: AgentCompletion,
    ) -> bool:
        """Evaluate Gate B and, on pass, materialise the agent's
        `output.files` into the artifacts surface (R-200-151). Returns
        True when the pipeline should advance (gate passed) ; False when
        the orchestrator should retry the generate phase (gate failed).
        Extracted from `_run_phase` to keep the state-machine loop's
        branch count below ruff's threshold (PLR0912)."""
        gate_b = await self._domain.evaluate_gate_b(
            row["run_id"], dict(completion.output),
        )
        if not gate_b.passed:
            await self._handle_gate_failure(row, Phase.GENERATE, gate_b)
            return False
        await self._publish(
            row["run_id"],
            "gate.passed",
            {"gate": gate_b.gate.value, "artifact_id": gate_b.artifact_id},
        )
        # R-200-151 : materialise generate-phase files into the
        # artifacts surface on the first successful generate. The
        # `artifacts_materialised` flag is the de-dup key — gate
        # failures + three-fix retries land in the same run_id and
        # would otherwise materialise N copies.
        if not row.get("artifacts_materialised"):
            await self._materialise_generate_output(row, completion)
        return True

    # ------------------------------------------------------------------
    # Artifact materialisation (R-200-150..152)
    # ------------------------------------------------------------------

    async def _materialise_generate_output(
        self, row: dict[str, Any], completion: AgentCompletion,
    ) -> None:
        """Translate the agent's `output.files` list into ArtifactsService
        calls (create_run -> put_file x N -> mark_completed). Best-effort :
        any failure logs a WARNING and returns ; the orchestrator does NOT
        block the run on materialisation problems (R-200-152). The
        `mark_completed(COMPLETED)` call triggers the Gitea push wired
        into ArtifactsService at Pass 2.2 (R-200-146)."""
        if self._artifacts is None:
            return  # legacy/test setup without artifacts surface — silent skip
        files_raw = completion.output.get("files")
        if not isinstance(files_raw, list) or not files_raw:
            _log.info(
                "generate completion has no `files` to materialise (run=%s)",
                row["run_id"],
            )
            return
        run_id = str(row["run_id"])
        project_id = str(row["project_id"])
        tenant_id = str(row["tenant_id"])
        try:
            await self._artifacts.create_run(
                project_id=project_id,
                tenant_id=tenant_id,
                run_id=run_id,
                label=f"generate run {run_id[:8]}",
            )
        except Exception as exc:
            _log.warning(
                "artifacts.create_run failed (run=%s): %s — skipping materialisation",
                run_id, exc,
            )
            return
        written = 0
        for entry in files_raw:
            if not isinstance(entry, dict):
                continue
            # Accept common synonyms used by small open models : qwen2.5
            # emits `name`/`contents`, some Llama variants use
            # `filename`/`body` or `path`/`source`. Normalise here so
            # downstream code keeps reading `path` / `content`.
            path = (
                entry.get("path")
                or entry.get("name")
                or entry.get("filename")
                or entry.get("file")
            )
            content = (
                entry.get("content")
                or entry.get("contents")
                or entry.get("body")
                or entry.get("source")
                or entry.get("code")
            )
            if not isinstance(path, str) or not isinstance(content, str):
                _log.warning(
                    "skipping malformed file entry in generate output (run=%s): %r",
                    run_id, entry,
                )
                continue
            try:
                await self._artifacts.put_file(
                    run_id=run_id,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    relative_path=path,
                    data=content.encode("utf-8"),
                )
                written += 1
            except Exception as exc:
                _log.warning(
                    "artifacts.put_file failed (run=%s, path=%s): %s",
                    run_id, path, exc,
                )
                continue
        try:
            await self._artifacts.mark_completed(
                run_id=run_id, status_=ArtifactRunStatus.COMPLETED,
            )
        except Exception as exc:
            _log.warning(
                "artifacts.mark_completed failed (run=%s): %s",
                run_id, exc,
            )
        row["artifacts_materialised"] = True
        row["artifacts_files_written"] = written
        await self._repo.upsert_run(row)
        await self._publish(
            run_id,
            "artifacts.materialised",
            {"files_written": written, "artifact_run_id": run_id},
        )

    # ------------------------------------------------------------------
    # NATS event fan-out (R-200-070)
    # ------------------------------------------------------------------

    async def _publish(
        self, run_id: str, action_suffix: str, payload: dict[str, Any]
    ) -> None:
        subject = f"orchestrator.{run_id}.{action_suffix}"
        envelope = {
            "event_id": str(uuid.uuid4()),
            "event_type": subject,
            "event_version": 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "payload": payload,
        }
        await self._publisher.publish(subject, envelope)


# ---------------------------------------------------------------------------
# FastAPI dependency + row→public projection
# ---------------------------------------------------------------------------


def get_service(request: Request) -> OrchestratorService:
    svc = getattr(request.app.state, "orchestrator_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="orchestrator service not initialised",
        )
    return svc  # type: ignore[no-any-return]


def _public(row: dict[str, Any]) -> RunPublic:
    return RunPublic(
        run_id=row["run_id"],
        project_id=row["project_id"],
        session_id=row["session_id"],
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        domain=row["domain"],
        current_phase=Phase(row["current_phase"]),
        status=RunStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=(
            datetime.fromisoformat(row["completed_at"])
            if row.get("completed_at")
            else None
        ),
        concerns=[
            AgentConcern(
                severity=str(c["severity"]),
                message=str(c["message"]),
            )
            for c in row.get("concerns", [])
            if isinstance(c, dict)
        ],
        minio_root=row["minio_root"],
        block_reason=(
            str(row["block_reason"])
            if row.get("block_reason") is not None
            else None
        ),
    )
