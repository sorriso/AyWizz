# =============================================================================
# File: test_upload_pipeline.py
# Version: 1
# Path: ay_platform_core/tests/integration/c7_memory/test_upload_pipeline.py
# Description: Phase B integration tests — file upload + parser pipeline.
#              For each supported MIME type (text/plain, text/markdown,
#              text/html, application/pdf, OpenXML DOCX) the test:
#
#                1. Builds a small fixture file in memory.
#                2. POSTs it to /api/v1/memory/projects/{p}/sources/upload.
#                3. Asserts the source row landed in Arango with
#                   chunk_count > 0.
#                4. Asserts the raw blob landed in MinIO and the bytes
#                   round-trip.
#                5. (Some types) asserts a known phrase is present in
#                   one of the chunks — proves the parser actually
#                   extracted the text body.
#
# @relation validates:R-400-021
# =============================================================================

from __future__ import annotations

import asyncio
import io
import uuid

import httpx
import pytest
from docx import Document as DocxDocument
from fastapi import FastAPI
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.storage.minio_storage import MemorySourceStorage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="function")]


_TENANT = "tenant-upload"
_PROJECT = "project-upload"
_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _headers() -> dict[str, str]:
    return {
        "X-User-Id": "u-upload",
        "X-Tenant-Id": _TENANT,
        "X-User-Roles": "project_editor",
    }


async def _upload(
    app: FastAPI,
    *,
    source_id: str,
    mime_type: str,
    data: bytes,
    filename: str,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post(
            f"/api/v1/memory/projects/{_PROJECT}/sources/upload",
            headers=_headers(),
            data={"source_id": source_id, "mime_type": mime_type},
            files={"file": (filename, data, mime_type)},
        )


async def _assert_chunks_exist_in_arango(
    repo: MemoryRepository, source_id: str, expected_phrase: str | None,
) -> None:
    """Run an AQL query directly to confirm chunks were indexed and
    optionally that they contain a known phrase."""

    def _q() -> list[dict[str, object]]:
        cursor = repo._db.aql.execute(
            "FOR c IN memory_chunks "
            "FILTER c.tenant_id == @tid AND c.project_id == @pid "
            "AND c.source_id == @sid "
            "RETURN c",
            bind_vars={"tid": _TENANT, "pid": _PROJECT, "sid": source_id},
        )
        return list(cursor)

    rows = await asyncio.to_thread(_q)
    assert len(rows) > 0, f"no chunks indexed for source_id={source_id}"
    if expected_phrase is not None:
        joined = " ".join(str(r["content"]) for r in rows)
        assert expected_phrase in joined, (
            f"expected phrase {expected_phrase!r} not found in any chunk; "
            f"got {len(rows)} chunks: "
            f"{[str(r['content'])[:80] for r in rows]}"
        )


async def _assert_blob_round_trips(
    storage: MemorySourceStorage,
    source_id: str,
    mime_type: str,
    original: bytes,
) -> None:
    blob = await storage.get_source_blob(
        tenant_id=_TENANT,
        project_id=_PROJECT,
        source_id=source_id,
        mime_type=mime_type,
    )
    assert blob == original, (
        f"blob round-trip mismatch for {source_id}: "
        f"sent {len(original)} bytes, got back {len(blob)} bytes"
    )


# ---------------------------------------------------------------------------
# text/plain
# ---------------------------------------------------------------------------


async def test_upload_text_plain(
    c7_upload_app: FastAPI,
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
) -> None:
    source_id = f"src-txt-{uuid.uuid4().hex[:6]}"
    body = (
        b"The Voyager 1 spacecraft was launched in 1977 and is the most "
        b"distant human-made object from Earth, currently in interstellar "
        b"space and still transmitting data."
    )
    response = await _upload(
        c7_upload_app, source_id=source_id, mime_type="text/plain",
        data=body, filename="voyager.txt",
    )
    assert response.status_code == 201, response.text
    await _assert_chunks_exist_in_arango(c7_repo, source_id, "Voyager 1")
    await _assert_blob_round_trips(c7_storage, source_id, "text/plain", body)


# ---------------------------------------------------------------------------
# text/markdown
# ---------------------------------------------------------------------------


async def test_upload_text_markdown_strips_frontmatter(
    c7_upload_app: FastAPI,
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
) -> None:
    """The Markdown parser SHALL strip the YAML frontmatter so the
    indexed chunks contain only the prose body."""
    source_id = f"src-md-{uuid.uuid4().hex[:6]}"
    body = (
        b"---\n"
        b"title: Test Document\n"
        b"author: pytest\n"
        b"---\n"
        b"\n"
        b"# Heading\n\n"
        b"The Eiffel Tower stands 330 meters tall and was completed in 1889.\n"
    )
    response = await _upload(
        c7_upload_app, source_id=source_id, mime_type="text/markdown",
        data=body, filename="doc.md",
    )
    assert response.status_code == 201, response.text
    await _assert_chunks_exist_in_arango(c7_repo, source_id, "Eiffel Tower")

    def _q() -> str:
        cursor = c7_repo._db.aql.execute(
            "FOR c IN memory_chunks FILTER c.source_id == @sid RETURN c.content",
            bind_vars={"sid": source_id},
        )
        return " ".join(list(cursor))

    joined = await asyncio.to_thread(_q)
    assert "title: Test Document" not in joined, (
        "frontmatter leaked into indexed chunks"
    )
    await _assert_blob_round_trips(c7_storage, source_id, "text/markdown", body)


# ---------------------------------------------------------------------------
# text/html
# ---------------------------------------------------------------------------


async def test_upload_text_html_strips_scripts_and_style(
    c7_upload_app: FastAPI,
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
) -> None:
    source_id = f"src-html-{uuid.uuid4().hex[:6]}"
    body = (
        b"<html><head>"
        b"<style>body { color: red; }</style>"
        b"<script>alert('xss')</script>"
        b"</head><body>"
        b"<h1>Helvetica</h1>"
        b"<p>The Helvetica typeface was designed in 1957 by Max Miedinger.</p>"
        b"</body></html>"
    )
    response = await _upload(
        c7_upload_app, source_id=source_id, mime_type="text/html",
        data=body, filename="page.html",
    )
    assert response.status_code == 201, response.text
    await _assert_chunks_exist_in_arango(c7_repo, source_id, "Helvetica typeface")

    def _q() -> str:
        cursor = c7_repo._db.aql.execute(
            "FOR c IN memory_chunks FILTER c.source_id == @sid RETURN c.content",
            bind_vars={"sid": source_id},
        )
        return " ".join(list(cursor))

    joined = await asyncio.to_thread(_q)
    assert "alert(" not in joined, "script content leaked into chunks"
    assert "color: red" not in joined, "style content leaked into chunks"
    await _assert_blob_round_trips(c7_storage, source_id, "text/html", body)


# ---------------------------------------------------------------------------
# application/pdf
# ---------------------------------------------------------------------------


def _make_pdf_bytes(text_pages: list[str]) -> bytes:
    """Build a minimal multi-page PDF in memory using pypdf's writer.

    pypdf cannot author rich text from scratch, so each page contains
    a single text block via the low-level `add_blank_page` + page text
    annotations approach. Simpler: synthesize PDF using a
    pre-baked stream that pypdf can re-read.
    """
    # Hand-crafted content stream — pypdf doesn't author rich text
    # itself, so we write the minimal "BT /F1 12 Tf … Tj ET" sequence
    # and attach a Helvetica font resource. Imports lifted to module
    # scope per ruff PLC0415.
    writer = PdfWriter()
    for page_text in text_pages:
        page = writer.add_blank_page(width=595, height=842)  # A4
        # Build a content stream: Begin Text, set font, draw at (50, 750).
        # Escape parens in the text per PDF string syntax.
        escaped = page_text.replace("(", "\\(").replace(")", "\\)")
        stream_data = (
            f"BT /F1 12 Tf 50 750 Td ({escaped}) Tj ET"
        ).encode("latin-1")
        content = DecodedStreamObject()
        content.set_data(stream_data)
        # Attach a font resource (Helvetica) so the text shows up extractable.
        font_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font_dict)
        resources = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(content)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def test_upload_application_pdf(
    c7_upload_app: FastAPI,
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
) -> None:
    source_id = f"src-pdf-{uuid.uuid4().hex[:6]}"
    pdf_bytes = _make_pdf_bytes([
        "Honeybees are eusocial flying insects that produce honey.",
        "Their colonies are organised into queen workers and drones.",
    ])
    response = await _upload(
        c7_upload_app, source_id=source_id, mime_type="application/pdf",
        data=pdf_bytes, filename="bees.pdf",
    )
    assert response.status_code == 201, response.text
    await _assert_chunks_exist_in_arango(c7_repo, source_id, "Honeybees")
    await _assert_blob_round_trips(
        c7_storage, source_id, "application/pdf", pdf_bytes,
    )


async def test_upload_corrupt_pdf_returns_422(
    c7_upload_app: FastAPI,
) -> None:
    """A non-PDF byte payload sent as `application/pdf` MUST be rejected
    with 422 (ParseFailureError) — not silently indexed as empty."""
    response = await _upload(
        c7_upload_app,
        source_id=f"src-bad-{uuid.uuid4().hex[:6]}",
        mime_type="application/pdf",
        data=b"this is plainly not a PDF",
        filename="bad.pdf",
    )
    assert response.status_code == 422
    assert "invalid PDF" in response.json()["detail"]


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def test_upload_application_docx(
    c7_upload_app: FastAPI,
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
) -> None:
    source_id = f"src-docx-{uuid.uuid4().hex[:6]}"
    docx_bytes = _make_docx_bytes([
        "Architecture review of the platform.",
        "The Pyrenees mountain range separates France from Spain.",
        "Key topics include scalability and tenant isolation.",
    ])
    response = await _upload(
        c7_upload_app, source_id=source_id, mime_type=_DOCX_MIME,
        data=docx_bytes, filename="review.docx",
    )
    assert response.status_code == 201, response.text
    await _assert_chunks_exist_in_arango(c7_repo, source_id, "Pyrenees")
    await _assert_blob_round_trips(c7_storage, source_id, _DOCX_MIME, docx_bytes)


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------


async def test_upload_unsupported_mime_returns_415(
    c7_upload_app: FastAPI,
) -> None:
    response = await _upload(
        c7_upload_app,
        source_id="src-bad-mime",
        mime_type="application/x-not-supported",
        data=b"opaque",
        filename="x.bin",
    )
    assert response.status_code == 415
    assert "no parser registered" in response.json()["detail"]
