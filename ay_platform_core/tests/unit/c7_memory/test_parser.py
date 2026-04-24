# =============================================================================
# File: test_parser.py
# Version: 1
# Path: ay_platform_core/tests/unit/c7_memory/test_parser.py
# Description: Unit tests for the MIME-dispatching parser.
# =============================================================================

from __future__ import annotations

import pytest

from ay_platform_core.c7_memory.ingestion import parser as _parser_module
from ay_platform_core.c7_memory.ingestion.parser import (
    UnsupportedMimeError,
    parse,
    register_parser,
)


@pytest.mark.unit
class TestParser:
    def test_plain_text_passthrough(self) -> None:
        out = parse("text/plain", b"hello world")
        assert out == "hello world"

    def test_markdown_strips_frontmatter(self) -> None:
        md = b"---\nkey: value\n---\n# Title\n\nBody."
        out = parse("text/markdown", md)
        assert out.startswith("# Title")
        assert "key: value" not in out

    def test_markdown_without_frontmatter_is_unchanged(self) -> None:
        md = b"# Title\n\nBody."
        out = parse("text/markdown", md)
        assert out == "# Title\n\nBody."

    def test_unknown_mime_raises(self) -> None:
        with pytest.raises(UnsupportedMimeError):
            parse("application/x-custom", b"anything")

    def test_pdf_raises_not_implemented_by_default(self) -> None:
        with pytest.raises(NotImplementedError, match="memory-pdf"):
            parse("application/pdf", b"%PDF-1.4")

    def test_image_raises_not_implemented_by_default(self) -> None:
        with pytest.raises(NotImplementedError, match="memory-ocr"):
            parse("image/png", b"\x89PNG")

    def test_register_parser_enables_new_mime(self) -> None:
        # Register a custom parser at runtime (operator hook) then parse.
        register_parser("text/custom", lambda b: b.decode("utf-8").upper())
        try:
            out = parse("text/custom", b"hello")
            assert out == "HELLO"
        finally:
            # Remove so the registry stays clean for other tests.
            _parser_module._REGISTRY.pop("text/custom", None)
