"""Text extraction from uploaded files (PDF, Markdown, plain text)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("meeting-proxy.materials")


def extract_text(file_path: str, mime_type: str | None = None) -> str:
    """Extract text content from a file based on its type."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" or (mime_type and "pdf" in mime_type):
        return _extract_pdf(path)
    if suffix in (".md", ".txt", ".markdown"):
        return _extract_plaintext(path)

    logger.warning("Unsupported file type for extraction: %s", suffix)
    return ""


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using PyPDF2."""
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        result = "\n\n".join(pages)
        logger.info("Extracted %d chars from PDF %s (%d pages)", len(result), path.name, len(reader.pages))
        return result
    except ImportError:
        logger.error("PyPDF2 not installed, cannot extract PDF text")
        return ""
    except Exception:
        logger.exception("Failed to extract text from PDF: %s", path)
        return ""


def _extract_plaintext(path: Path) -> str:
    """Read plain text / markdown files."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        logger.info("Extracted %d chars from %s", len(text), path.name)
        return text
    except Exception:
        logger.exception("Failed to read text file: %s", path)
        return ""


def extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Extract text from in-memory content based on filename extension."""
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        try:
            import io

            from PyPDF2 import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages = [p.extract_text() or "" for p in reader.pages]
            return "\n\n".join(p.strip() for p in pages if p.strip())
        except ImportError:
            logger.error("PyPDF2 not installed")
            return ""
        except Exception:
            logger.exception("Failed to extract PDF from bytes")
            return ""

    if suffix in (".md", ".txt", ".markdown"):
        return content.decode("utf-8", errors="replace").strip()

    return ""
