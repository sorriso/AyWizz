# =============================================================================
# File: test_documents_api.py
# Version: 1
# Path: ay_platform_core/tests/integration/c4_orchestrator/test_documents_api.py
# Description: Integration tests for the chat-direct DocGen document
#              CRUD surface (D-015 / R-200-153..156). Exercises
#              POST / PUT / GET (list + read) / DELETE end-to-end
#              against real ArangoDB + real MinIO testcontainers and a
#              stubbed Gitea client, through the FastAPI router.
# =============================================================================

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from arango import ArangoClient  # type: ignore[attr-defined]
from fastapi import FastAPI
from minio import Minio

from ay_platform_core.c4_orchestrator.artifacts_service import ArtifactsService
from ay_platform_core.c4_orchestrator.artifacts_storage import ArtifactStorage
from ay_platform_core.c4_orchestrator.db.repository import OrchestratorRepository
from ay_platform_core.c4_orchestrator.documents_router import (
    router as documents_router,
)
from tests.fixtures.containers import (
    ArangoEndpoint,
    MinioEndpoint,
    cleanup_arango_database,
)
from tests.integration.c2_auth.test_gitea_provisioning import _FakeGiteaClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="function")]


_HEADERS = {
    "X-User-Id": "alice",
    "X-Tenant-Id": "tenant-doc",
    "X-User-Roles": "project_editor,admin",
}
_HEADERS_TENANT_MANAGER = {
    "X-User-Id": "tm",
    "X-Tenant-Id": "tenant-doc",
    "X-User-Roles": "tenant_manager",
}


@pytest_asyncio.fixture(scope="function")
async def documents_app(
    arango_container: ArangoEndpoint,
    minio_container: MinioEndpoint,
) -> AsyncIterator[tuple[FastAPI, _FakeGiteaClient]]:
    db_name = f"c4_doc_{uuid.uuid4().hex[:8]}"
    bucket = f"docbucket-{uuid.uuid4().hex[:8]}"
    sys_db = ArangoClient(hosts=arango_container.url).db(
        "_system", username="root", password=arango_container.password,
    )
    sys_db.create_database(db_name)
    db = ArangoClient(hosts=arango_container.url).db(
        db_name, username="root", password=arango_container.password,
    )
    repo = OrchestratorRepository(db)
    repo._ensure_collections_sync()

    minio_client = Minio(
        minio_container.endpoint,
        access_key=minio_container.access_key,
        secret_key=minio_container.secret_key,
        secure=False,
    )
    storage = ArtifactStorage(minio_client, bucket)
    await storage.ensure_bucket()
    fake_gitea = _FakeGiteaClient()
    service = ArtifactsService(
        repo=repo, storage=storage, gitea=fake_gitea,  # type: ignore[arg-type]
    )

    app = FastAPI()
    app.include_router(documents_router)
    app.state.artifacts_service = service
    try:
        yield app, fake_gitea
    finally:
        cleanup_arango_database(arango_container, db_name)


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://e2e-doc",
    )


# ---------------------------------------------------------------------------
# CRUD happy path + Gitea push
# ---------------------------------------------------------------------------


async def test_full_document_lifecycle(
    documents_app: tuple[FastAPI, _FakeGiteaClient],
) -> None:
    """R-200-153..155 : create → list → read → update → delete, with
    incremental Gitea push observed on each write."""
    app, fake_gitea = documents_app
    async with _client(app) as c:
        # Empty list before any write.
        listing = await c.get(
            "/api/v1/projects/proj-d/documents", headers=_HEADERS,
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["documents"] == []

        # Create.
        created = await c.post(
            "/api/v1/projects/proj-d/documents",
            headers=_HEADERS,
            json={"path": "docs/intro.md", "content": "# Intro\n\nHello.\n"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["path"] == "docs/intro.md"
        assert body["size_bytes"] > 0

        # Gitea push fired (one commit). Owner is svc-{tenant}-{project}.
        key = ("svc-tenant-doc-proj-d", "proj-d")
        assert key in fake_gitea.files
        assert fake_gitea.files[key]["docs/intro.md"] == b"# Intro\n\nHello.\n"
        assert len(fake_gitea.commits.get(key, [])) == 1

        # List shows the doc.
        listing = await c.get(
            "/api/v1/projects/proj-d/documents", headers=_HEADERS,
        )
        assert listing.status_code == 200
        paths = {d["path"] for d in listing.json()["documents"]}
        assert paths == {"docs/intro.md"}

        # Read returns the content.
        read = await c.get(
            "/api/v1/projects/proj-d/documents/docs/intro.md",
            headers=_HEADERS,
        )
        assert read.status_code == 200, read.text
        assert read.text == "# Intro\n\nHello.\n"

        # Update via PUT — overwrites + new Gitea commit.
        updated = await c.put(
            "/api/v1/projects/proj-d/documents/docs/intro.md",
            headers=_HEADERS,
            json={"content": "# Intro v2\n\nUpdated.\n"},
        )
        assert updated.status_code == 200, updated.text
        read2 = await c.get(
            "/api/v1/projects/proj-d/documents/docs/intro.md",
            headers=_HEADERS,
        )
        assert read2.text == "# Intro v2\n\nUpdated.\n"
        assert len(fake_gitea.commits.get(key, [])) == 2

        # Delete — 204, then 404 on subsequent read.
        deleted = await c.delete(
            "/api/v1/projects/proj-d/documents/docs/intro.md",
            headers=_HEADERS,
        )
        assert deleted.status_code == 204, deleted.text
        gone = await c.get(
            "/api/v1/projects/proj-d/documents/docs/intro.md",
            headers=_HEADERS,
        )
        assert gone.status_code == 404
        listing = await c.get(
            "/api/v1/projects/proj-d/documents", headers=_HEADERS,
        )
        assert listing.json()["documents"] == []


async def test_path_traversal_rejected(
    documents_app: tuple[FastAPI, _FakeGiteaClient],
) -> None:
    """R-200-153 : `..` / leading `/` / backslash SHALL be 400."""
    app, _ = documents_app
    async with _client(app) as c:
        for bad in ("../escape.md", "a\\b.md"):
            r = await c.post(
                "/api/v1/projects/proj-d/documents",
                headers=_HEADERS,
                json={"path": bad, "content": "x"},
            )
            assert r.status_code == 400, f"{bad!r} should be 400 (got {r.status_code})"


async def test_tenant_manager_rejected(
    documents_app: tuple[FastAPI, _FakeGiteaClient],
) -> None:
    """E-100-002 v2 : tenant_manager is content-blind → 403 on every
    document verb."""
    app, _ = documents_app
    async with _client(app) as c:
        assert (
            await c.get(
                "/api/v1/projects/proj-d/documents",
                headers=_HEADERS_TENANT_MANAGER,
            )
        ).status_code == 403
        assert (
            await c.post(
                "/api/v1/projects/proj-d/documents",
                headers=_HEADERS_TENANT_MANAGER,
                json={"path": "x.md", "content": "y"},
            )
        ).status_code == 403


async def test_read_missing_document_404(
    documents_app: tuple[FastAPI, _FakeGiteaClient],
) -> None:
    """A path that was never written → 404 (run exists check + blob
    miss). Also covers the no-run-yet case (list-empty → read 404)."""
    app, _ = documents_app
    async with _client(app) as c:
        # No run yet at all.
        r = await c.get(
            "/api/v1/projects/proj-d/documents/never.md", headers=_HEADERS,
        )
        assert r.status_code == 404
        # Create one doc, then read a different missing path.
        await c.post(
            "/api/v1/projects/proj-d/documents",
            headers=_HEADERS,
            json={"path": "a.md", "content": "a"},
        )
        r2 = await c.get(
            "/api/v1/projects/proj-d/documents/b.md", headers=_HEADERS,
        )
        assert r2.status_code == 404


async def test_gitea_failure_does_not_break_write(
    documents_app: tuple[FastAPI, _FakeGiteaClient],
) -> None:
    """R-200-155 best-effort : a Gitea outage SHALL NOT fail the write
    — MinIO stays the source of truth."""
    app, fake_gitea = documents_app
    fake_gitea.fail_on_create_file = True
    async with _client(app) as c:
        created = await c.post(
            "/api/v1/projects/proj-d/documents",
            headers=_HEADERS,
            json={"path": "resilient.md", "content": "still saved"},
        )
        assert created.status_code == 201, created.text
        # MinIO read still works despite the Gitea failure.
        read = await c.get(
            "/api/v1/projects/proj-d/documents/resilient.md",
            headers=_HEADERS,
        )
        assert read.status_code == 200
        assert read.text == "still saved"
        # No commit landed on the stub (it raised on every call).
        key = ("svc-tenant-doc-proj-d", "proj-d")
        assert fake_gitea.commits.get(key, []) == []
