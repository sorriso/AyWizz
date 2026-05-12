#!/usr/bin/env python3
# =============================================================================
# File: seed_demo_ux.py
# Version: 2
# Path: ay_platform_core/scripts/seed_demo_ux.py
# Description: Post-stack demo data seeder for the manual-test stack
#              brought up by `e2e_stack.sh dev`. Distinct from
#              `seed_e2e.py` (which targets the `demo` project for the
#              pytest e2e suite) — this one targets the `project-test`
#              that C2's `_ensure_demo_seed()` provisioned at lifespan
#              start, and uses the `tenant-admin` credentials surfaced
#              on /ux/config.
#
#              v2 (2026-05-11) : Phase D + E seeds — 1 empty C3
#              conversation (the operator chats it) and 1 C5
#              requirements document (so /requirements isn't empty).
#              Phase C source seed (v1) stays.
#
# Usage:
#   python ay_platform_core/scripts/seed_demo_ux.py [--base-url URL]
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:56000"
TENANT_ID = "tenant-test"
PROJECT_ID = "project-test"
ADMIN_USERNAME = "tenant-admin"
ADMIN_PASSWORD = "dev-tenant"

# Sample source corpus — small text files so the parse → chunk → embed
# pipeline runs in well under a second. Each entry yields one row in the
# Sources page.
DEMO_CONVERSATION_TITLE = "Welcome to the test project"
DEMO_DOC_SLUG = "900-SPEC-DEMO"
DEMO_DOC_BODY = """---
document: 900-SPEC-DEMO
version: 1
path: projects/project-test/requirements/900-SPEC-DEMO.md
language: en
status: draft
---

# Demo spec for the manual-test stack

This document is seeded by `seed_demo_ux.py` so the **Requirements**
section has at least one entry to render. Replace or delete freely.

#### R-900-001

```yaml
id: R-900-001
version: 1
status: approved
category: functional
```

The platform SHALL allow project editors to browse seeded requirements
through the C5 read-only surface.
"""


DEMO_SOURCES: list[dict[str, str]] = [
    {
        "source_id": "demo-readme",
        "mime_type": "text/markdown",
        "filename": "README.md",
        "content": (
            "# AyWizz Test Project\n\n"
            "This is a demo source seeded by `seed_demo_ux.py`.\n\n"
            "## What it's for\n\n"
            "- Validate the **Sources** section renders with non-empty data\n"
            "- Exercise C7's Markdown parser end-to-end\n"
            "- Provide a known corpus for `chat with RAG` demos\n\n"
            "Edit me, replace me, or delete me — the seed is idempotent.\n"
        ),
    },
    {
        "source_id": "demo-platform-note",
        "mime_type": "text/plain",
        "filename": "platform-note.txt",
        "content": (
            "AyWizz platform — quick orientation note.\n\n"
            "Architecture is built around a domain-agnostic backbone\n"
            "with pluggable production domains. v1 ships the `code`\n"
            "profile only ; future profiles (data, doc, etc.) will\n"
            "plug into the same shell without UX rebuilds.\n\n"
            "The auth model has 5 roles : tenant_manager (super-root,\n"
            "content-blind), admin / tenant_admin, project_owner,\n"
            "project_editor, project_viewer.\n"
        ),
    },
]


class SeedError(RuntimeError):
    """Raised when the seeder cannot complete because the stack is unreachable or
    the seed data conflicts irrecoverably."""


async def wait_stack_ready(
    base_url: str, *, timeout_s: float, poll_interval_s: float = 1.0
) -> None:
    """Block until `/ux/config` returns 200 AND `dev_credentials`
    is populated (which means C2's `_ensure_demo_seed` has run)."""
    deadline = time.monotonic() + timeout_s
    last_err: str | None = None
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{base_url}/ux/config")
                if resp.status_code == 200:
                    body = resp.json()
                    creds = body.get("dev_credentials") or []
                    if creds:
                        return
                    last_err = "/ux/config 200 but dev_credentials empty"
                else:
                    last_err = f"/ux/config -> HTTP {resp.status_code}"
            except httpx.RequestError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(poll_interval_s)
    raise SeedError(f"stack never became ready: {last_err!r}")


async def obtain_token(client: httpx.AsyncClient, base_url: str) -> str:
    """Login as the demo `tenant-admin` (has `admin` role, full r/w in
    `tenant-test`). Credentials match `C2_DEMO_SEED_TENANT_ADMIN_*`."""
    resp = await client.post(
        f"{base_url}/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    if resp.status_code != 200:
        raise SeedError(
            f"/auth/login as {ADMIN_USERNAME} failed: "
            f"{resp.status_code} {resp.text}"
        )
    token = resp.json().get("access_token")
    if not token:
        raise SeedError(f"no access_token in /auth/login response: {resp.text}")
    return str(token)


async def ensure_demo_conversation(
    client: httpx.AsyncClient, base_url: str, token: str,
) -> str:
    """Create one empty C3 conversation scoped to project-test.
    Returns "created" / "exists" — `exists` when a conversation with
    the same title already lives under the caller."""
    headers = {"Authorization": f"Bearer {token}"}
    # Check existing conversations first (idempotency).
    resp_list = await client.get(
        f"{base_url}/api/v1/conversations", headers=headers,
    )
    if resp_list.status_code == 200:
        existing = resp_list.json().get("conversations", [])
        for c in existing:
            if (
                c.get("project_id") == PROJECT_ID
                and c.get("title") == DEMO_CONVERSATION_TITLE
            ):
                return "exists"

    resp = await client.post(
        f"{base_url}/api/v1/conversations",
        json={"title": DEMO_CONVERSATION_TITLE, "project_id": PROJECT_ID},
        headers=headers,
    )
    if resp.status_code != 201:
        raise SeedError(
            f"create conversation failed: {resp.status_code} {resp.text}"
        )
    return "created"


async def ensure_demo_requirements_doc(
    client: httpx.AsyncClient, base_url: str, token: str,
) -> str:
    """Create + populate a single demo requirements document in C5.
    Two-step (POST then PUT) per C5's API. Idempotent : a 409 on
    create maps to `exists` ; a 412/428 etag mismatch on PUT maps to
    `exists` (already seeded with this content)."""
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await client.post(
        f"{base_url}/api/v1/projects/{PROJECT_ID}/requirements/documents",
        json={"slug": DEMO_DOC_SLUG},
        headers=headers,
    )
    if create_resp.status_code not in (201, 409):
        raise SeedError(
            f"create doc failed: {create_resp.status_code} {create_resp.text}"
        )

    put_headers = {**headers, "If-Match": f'"{DEMO_DOC_SLUG}@v1"'}
    put_resp = await client.put(
        f"{base_url}/api/v1/projects/{PROJECT_ID}/requirements/documents/{DEMO_DOC_SLUG}",
        json={"content": DEMO_DOC_BODY},
        headers=put_headers,
    )
    if put_resp.status_code == 200:
        return "created"
    if put_resp.status_code in (412, 428):
        return "exists"
    raise SeedError(f"put doc failed: {put_resp.status_code} {put_resp.text}")


async def ensure_demo_source(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    entry: dict[str, str],
) -> str:
    """Upload one demo source via the multipart endpoint.

    Returns "created", "exists", or raises. C7 returns 409 when the
    `source_id` already exists in this project — idempotent on re-run.
    """
    headers = {"Authorization": f"Bearer {token}"}
    # multipart form : file, source_id, mime_type
    files = {
        "file": (
            entry["filename"],
            entry["content"].encode("utf-8"),
            entry["mime_type"],
        ),
    }
    data = {
        "source_id": entry["source_id"],
        "mime_type": entry["mime_type"],
    }
    resp = await client.post(
        f"{base_url}/api/v1/memory/projects/{PROJECT_ID}/sources/upload",
        files=files,
        data=data,
        headers=headers,
    )
    if resp.status_code == 201:
        return "created"
    if resp.status_code == 409:
        return "exists"
    raise SeedError(
        f"upload source {entry['source_id']!r} failed: "
        f"{resp.status_code} {resp.text}"
    )


async def run(args: argparse.Namespace) -> int:
    print(f"==> Waiting for stack at {args.base_url}…")
    await wait_stack_ready(args.base_url, timeout_s=args.timeout_s)

    print(f"==> Logging in as {ADMIN_USERNAME}…")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await obtain_token(client, args.base_url)

        print(f"==> Seeding {len(DEMO_SOURCES)} source(s) into {PROJECT_ID}…")
        results: dict[str, list[str]] = {"created": [], "exists": []}
        for entry in DEMO_SOURCES:
            try:
                outcome = await ensure_demo_source(client, args.base_url, token, entry)
                results[outcome].append(entry["source_id"])
                print(f"   [{outcome}] source/{entry['source_id']}")
            except SeedError as exc:
                # Non-fatal on individual sources — keep going. C7 may
                # transiently reject (e.g. if Ollama is still warming).
                print(f"   [error] source/{entry['source_id']}: {exc}", file=sys.stderr)

        # Phase D : seed one empty conversation so /conversations is
        # non-empty. The operator chats it manually.
        try:
            outcome = await ensure_demo_conversation(client, args.base_url, token)
            results[outcome].append(f"conversation/{DEMO_CONVERSATION_TITLE!r}")
            print(f"   [{outcome}] conversation: {DEMO_CONVERSATION_TITLE!r}")
        except SeedError as exc:
            print(f"   [error] conversation: {exc}", file=sys.stderr)

        # Phase E : seed one requirements document so /requirements
        # has something to render.
        try:
            outcome = await ensure_demo_requirements_doc(client, args.base_url, token)
            results[outcome].append(f"doc/{DEMO_DOC_SLUG}")
            print(f"   [{outcome}] requirements doc: {DEMO_DOC_SLUG}")
        except SeedError as exc:
            print(f"   [error] requirements doc: {exc}", file=sys.stderr)

    summary: dict[str, Any] = {
        "base_url": args.base_url,
        "project_id": PROJECT_ID,
        "created": results["created"],
        "exists": results["exists"],
    }
    print("SEED DEMO UX OK:", summary)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed demo data for the manual-test UX stack."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Public Traefik URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=120.0,
        help="Stack readiness timeout in seconds.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    rc = asyncio.run(run(_parse_args()))
    sys.exit(rc)
