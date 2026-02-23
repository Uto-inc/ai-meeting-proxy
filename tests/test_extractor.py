"""Tests for materials text extraction."""

from materials.extractor import extract_text_from_bytes


def test_extract_text_from_md() -> None:
    content = b"# Hello\n\nThis is a test document."
    result = extract_text_from_bytes(content, "test.md")
    assert "Hello" in result
    assert "test document" in result


def test_extract_text_from_txt() -> None:
    content = b"Plain text content"
    result = extract_text_from_bytes(content, "notes.txt")
    assert result == "Plain text content"


def test_extract_text_empty_file() -> None:
    result = extract_text_from_bytes(b"", "empty.txt")
    assert result == ""


def test_extract_unsupported_type() -> None:
    result = extract_text_from_bytes(b"data", "image.png")
    assert result == ""
