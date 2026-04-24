# =============================================================================
# File: parser.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c7_memory/ingestion/parser.py
# Description: MIME-type dispatching parsers. v1 implements text/plain and
#              text/markdown natively. PDF and image OCR are stubs that
#              raise NotImplementedError — Q-400-001/002 selects the
#              production libraries. Activation is gated by feature flags
#              so an operator can enable them once the chosen library is
#              installed.
#
# @relation implements:R-400-021
# =============================================================================

from __future__ import annotations

import re
from collections.abc import Callable

# Markdown frontmatter fence (`--- ... ---` at file start).
_FRONTMATTER_FENCE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


class UnsupportedMimeError(RuntimeError):
    """Raised by the dispatcher when no parser is installed for a MIME type."""


def parse(mime_type: str, content: bytes) -> str:
    """Dispatch to the parser matching `mime_type`.

    Returns the extracted plain text. Any failure raises — the caller
    (ingestion service) maps that to a `failed` source record.
    """
    parser = _REGISTRY.get(mime_type)
    if parser is None:
        raise UnsupportedMimeError(
            f"no parser registered for MIME type {mime_type!r}; "
            "v1 supports text/plain, text/markdown, application/pdf, "
            "image/png, image/jpeg (PDF + image OCR require optional extras)"
        )
    return parser(content)


# ---------------------------------------------------------------------------
# Concrete parsers
# ---------------------------------------------------------------------------


def _parse_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _parse_markdown(content: bytes) -> str:
    """Strip the YAML frontmatter if present, keep the rest as-is."""
    text = content.decode("utf-8", errors="replace")
    return _FRONTMATTER_FENCE.sub("", text, count=1).lstrip()


def _parse_pdf(_content: bytes) -> str:
    """Q-400-001 stub: production library (pypdf/docling) is activated by
    installing the `memory-pdf` extra. Until the operator opts in, ingest
    of PDFs fails with a clear error rather than silently returning an
    empty document."""
    raise NotImplementedError(
        "PDF parsing is not enabled — install the `memory-pdf` extra and "
        "register the parser to use it (Q-400-001 deferred in v1)"
    )


def _parse_image(_content: bytes) -> str:
    """Q-400-002 stub: OCR (Tesseract baseline) activated via the
    `memory-ocr` extra."""
    raise NotImplementedError(
        "image OCR is not enabled — install the `memory-ocr` extra and "
        "register the parser to use it (Q-400-002 deferred in v1)"
    )


_REGISTRY: dict[str, Callable[[bytes], str]] = {
    "text/plain": _parse_text,
    "text/markdown": _parse_markdown,
    "application/pdf": _parse_pdf,
    "image/png": _parse_image,
    "image/jpeg": _parse_image,
}


def register_parser(mime_type: str, parser: Callable[[bytes], str]) -> None:
    """Operator hook to plug a concrete PDF/image parser at startup.

    Used when the `memory-pdf` or `memory-ocr` extra is installed — the
    startup script imports the concrete parser and registers it here.
    """
    _REGISTRY[mime_type] = parser
