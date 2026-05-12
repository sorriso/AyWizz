# =============================================================================
# File: artifacts_service.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/artifacts_service.py
# Description: Facade for the project-artifacts surface. Bridges the
#              Arango run metadata (R-200-132) and the MinIO blob
#              adapter (artifacts_storage.py). Enforces the
#              tenant-scoped invariant : a run's `tenant_id` SHALL
#              match the X-Tenant-Id of the caller ; mismatches map
#              to 404 (R-200-132 — no detail leak).
#
#              Two surfaces :
#                - Read API (router) : list_runs / get_tree / get_blob.
#                - Write API (seeder + future C4 pipeline hook) :
#                  create_run + put_file. The router does NOT expose
#                  these — only the seeder script and the C4 service
#                  call them.
#
# @relation implements:R-200-131
# @relation implements:R-200-132
# @relation implements:R-200-133
# =============================================================================

from __future__ import annotations

import mimetypes
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from ay_platform_core.c2_auth.gitea_client import GiteaClient, GiteaError
from ay_platform_core.c4_orchestrator.artifacts_models import (
    ArtifactNode,
    ArtifactRunPublic,
    ArtifactRunStatus,
    ArtifactTree,
)
from ay_platform_core.c4_orchestrator.artifacts_storage import (
    ArtifactBlob,
    ArtifactStorage,
)
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository


class ArtifactsService:
    """Read + write API for the artifacts surface. The router consumes
    the read methods ; the seeder + future C4 pipeline consume the
    write methods. Tenant guard is enforced uniformly here so the
    router stays minimal."""

    def __init__(
        self,
        repo: OrchestratorRepository,
        storage: ArtifactStorage,
        gitea: GiteaClient | None = None,
    ) -> None:
        self._repo = repo
        self._storage = storage
        # Optional Gitea client — when set, `mark_completed` pushes
        # every file in the run to the project's Gitea repo
        # (R-200-146). None disables the push (legacy stack without
        # Gitea ; artifacts stay in MinIO only).
        self._gitea = gitea

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def list_runs(
        self, *, project_id: str, tenant_id: str,
    ) -> list[ArtifactRunPublic]:
        rows = await self._repo.list_artifact_runs(tenant_id, project_id)
        return [_row_to_public(r) for r in rows]

    async def get_tree(
        self, *, run_id: str, project_id: str, tenant_id: str,
    ) -> ArtifactTree:
        run = await self._load_run_or_404(
            run_id=run_id, project_id=project_id, tenant_id=tenant_id,
        )
        try:
            raw = await self._storage.list_tree(
                tenant_id=run["tenant_id"],
                project_id=run["project_id"],
                run_id=run["_key"],
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"storage backend error: {exc}",
            ) from exc
        nodes = [_blob_to_node(path, size) for path, size in raw]
        # Stable sort (alphabetical on path) so the UX tree is
        # deterministic across reloads.
        nodes.sort(key=lambda n: n.path)
        return ArtifactTree(run_id=run["_key"], nodes=nodes)

    async def get_blob(
        self,
        *,
        run_id: str,
        project_id: str,
        tenant_id: str,
        relative_path: str,
    ) -> ArtifactBlob:
        run = await self._load_run_or_404(
            run_id=run_id, project_id=project_id, tenant_id=tenant_id,
        )
        try:
            return await self._storage.get_blob(
                tenant_id=run["tenant_id"],
                project_id=run["project_id"],
                run_id=run["_key"],
                relative_path=relative_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"file {relative_path!r} not found in run",
            ) from exc
        except ValueError as exc:
            # Path-shape violation : `..`, leading `/`, backslashes.
            # 400 — the client built a bad request, not a missing file.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"storage backend error: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Write API (seeder + future C4 pipeline hook)
    # ------------------------------------------------------------------

    async def create_run(
        self,
        *,
        project_id: str,
        tenant_id: str,
        label: str | None = None,
        status_: ArtifactRunStatus = ArtifactRunStatus.RUNNING,
        run_id: str | None = None,
    ) -> str:
        """Create a fresh artifact run row in Arango. Returns the
        run_id. The blob layout under MinIO is created lazily on the
        first `put_file` call (`make_bucket` is idempotent at startup).
        Used by the seeder and (eventually) by the C4 pipeline hook
        that materialises generated files."""
        rid = run_id or str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        doc = {
            "_key": rid,
            "run_id": rid,
            "project_id": project_id,
            "tenant_id": tenant_id,
            "started_at": now,
            "completed_at": None,
            "status": status_.value,
            "file_count": 0,
            "total_bytes": 0,
            "label": label,
        }
        await self._repo.upsert_artifact_run(doc)
        return rid

    async def put_file(
        self,
        *,
        run_id: str,
        project_id: str,
        tenant_id: str,
        relative_path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        """Persist one file under a run's MinIO prefix AND bump the
        run metadata's `file_count` + `total_bytes`. Idempotent on
        replays (overwrites the same key, recomputes the run totals
        from the listing rather than naive incrementing — pricey but
        bulletproof for the seeder use case)."""
        if content_type is None:
            content_type = (
                mimetypes.guess_type(relative_path)[0]
                or "application/octet-stream"
            )
        await self._storage.put_blob(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            relative_path=relative_path,
            data=data,
            content_type=content_type,
        )
        # Recompute totals from the MinIO listing — keeps the run
        # metadata consistent even if the same path is written twice.
        entries = await self._storage.list_tree(
            tenant_id=tenant_id, project_id=project_id, run_id=run_id,
        )
        existing = await self._repo.get_artifact_run(run_id) or {}
        existing.update(
            {
                "_key": run_id,
                "run_id": run_id,
                "project_id": project_id,
                "tenant_id": tenant_id,
                "file_count": len(entries),
                "total_bytes": sum(s for _, s in entries),
            }
        )
        # Default the started_at / status fields when the run was not
        # explicitly created via `create_run` first (defensive).
        existing.setdefault("started_at", datetime.now(UTC).isoformat())
        existing.setdefault("status", ArtifactRunStatus.RUNNING.value)
        existing.setdefault("completed_at", None)
        existing.setdefault("label", None)
        await self._repo.upsert_artifact_run(existing)

    async def mark_completed(
        self, *, run_id: str, status_: ArtifactRunStatus,
    ) -> None:
        """Flip a run's status + stamp completed_at, then push every
        file under the run's MinIO prefix to the project's Gitea repo
        (R-200-146). The push is best-effort : a Gitea failure logs a
        WARNING but does NOT roll back the Arango state. Called by
        the seeder at end of seeding ; the future C4 pipeline will
        call this the same way at run completion."""
        doc = await self._repo.get_artifact_run(run_id)
        if doc is None:
            raise RuntimeError(f"artifact run {run_id!r} not found")
        doc["status"] = status_.value
        doc["completed_at"] = datetime.now(UTC).isoformat()
        await self._repo.upsert_artifact_run(doc)
        # Best-effort Gitea push. Only fires when both the client is
        # wired AND the run reached `completed` (failed runs aren't
        # pushed — Gitea would otherwise mix half-baked output with
        # successful runs).
        if self._gitea is not None and status_ is ArtifactRunStatus.COMPLETED:
            await self._best_effort_push_to_gitea(doc)

    async def _best_effort_push_to_gitea(self, run_doc: dict[str, Any]) -> None:
        """Push every file under the run's MinIO prefix to the project's
        Gitea repo. The Gitea path mirrors the MinIO relative_path
        verbatim ; each file is its own commit (R-200-146). Failures
        log a WARNING and return — MinIO stays the source of truth."""
        import logging  # noqa: PLC0415 — keep import local to the rarely-taken path

        log = logging.getLogger("c4_orchestrator.artifacts")
        assert self._gitea is not None  # narrowed by caller
        tenant_id = str(run_doc["tenant_id"])
        project_id = str(run_doc["project_id"])
        run_id = str(run_doc["_key"])
        try:
            entries = await self._storage.list_tree(
                tenant_id=tenant_id, project_id=project_id, run_id=run_id,
            )
        except Exception as exc:
            log.warning(
                "gitea push (run=%s): failed to list MinIO tree: %s",
                run_id, exc,
            )
            return
        # Owner = the service-account user provisioned by C2 at project
        # creation (R-200-141). Compute deterministically from
        # (tenant, project) so we don't need to read c2_project_secrets.
        owner = f"svc-{tenant_id}-{project_id}"
        for relative_path, _size in entries:
            try:
                blob = await self._storage.get_blob(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    relative_path=relative_path,
                )
            except Exception as exc:
                log.warning(
                    "gitea push (run=%s, path=%s): MinIO read failed: %s",
                    run_id, relative_path, exc,
                )
                continue
            try:
                await self._gitea.create_or_update_file(
                    owner=owner,
                    repo=project_id,
                    path=relative_path,
                    content=blob.data,
                    message=f"run {run_id} — {relative_path}",
                )
            except GiteaError as exc:
                log.warning(
                    "gitea push (run=%s, path=%s) failed: %s",
                    run_id, relative_path, exc,
                )
                # Continue with the rest of the files — partial push
                # is better than no push.

    # ------------------------------------------------------------------
    # Commit listing (R-200-147) — read-only proxy to Gitea.
    # ------------------------------------------------------------------

    async def list_commits(
        self,
        *,
        project_id: str,
        tenant_id: str,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Return a paginated list of commits for the project's Gitea
        repo. Returns dicts (not a Pydantic model) so the router can
        serialise straight into the wire schema declared in
        artifacts_models. Empty when Gitea is not wired or the repo
        is empty."""
        if self._gitea is None:
            return []
        owner = f"svc-{tenant_id}-{project_id}"
        commits = await self._gitea.list_commits(
            owner=owner, repo=project_id, page=page, limit=50,
        )
        return [
            {
                "sha": c.sha,
                "message": c.message,
                "author_name": c.author_name,
                "author_email": c.author_email,
                "committed_at": c.committed_at,
            }
            for c in commits
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _load_run_or_404(
        self, *, run_id: str, project_id: str, tenant_id: str,
    ) -> dict[str, Any]:
        """Fetch the run document, asserting it belongs to the
        (tenant, project) tuple. Mismatch maps to 404 per R-200-132
        (avoid leaking existence to a foreign tenant)."""
        doc = await self._repo.get_artifact_run(run_id)
        if (
            doc is None
            or doc.get("tenant_id") != tenant_id
            or doc.get("project_id") != project_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"artifact run {run_id!r} not found",
            )
        return doc


def _row_to_public(row: dict[str, Any]) -> ArtifactRunPublic:
    """Map a raw Arango row to the public schema. `_key` is the
    canonical id ; `started_at` / `completed_at` are ISO strings that
    Pydantic v2 parses automatically into datetimes."""
    return ArtifactRunPublic(
        run_id=str(row["_key"]),
        project_id=str(row["project_id"]),
        tenant_id=str(row["tenant_id"]),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        status=ArtifactRunStatus(row["status"]),
        file_count=int(row.get("file_count") or 0),
        total_bytes=int(row.get("total_bytes") or 0),
        label=row.get("label") if isinstance(row.get("label"), str) else None,
    )


def _blob_to_node(relative_path: str, size: int) -> ArtifactNode:
    """Map a `(rel_path, size)` listing entry to the public node
    shape. MIME type is inferred from the extension — UX falls back
    to a generic icon when None."""
    mime, _ = mimetypes.guess_type(relative_path)
    # v1 surface only files ; pseudo-dirs are inferred client-side
    # from path segments.
    return ArtifactNode(
        path=relative_path,
        kind="file",
        size_bytes=size,
        mime_type=mime,
    )
