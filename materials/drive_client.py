"""Google Drive API wrapper for reading Docs, Sheets, and Slides content."""

from __future__ import annotations

import logging
from typing import Any

from googleapiclient.discovery import build

logger = logging.getLogger("meeting-proxy.materials")

# Maps Google Workspace MIME types to export formats
_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", "document"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "spreadsheet"),
    "application/vnd.google-apps.presentation": ("text/plain", "presentation"),
}


def build_drive_service(credentials: Any) -> Any:
    """Build a Google Drive API service."""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def get_file_metadata(service: Any, file_id: str) -> dict[str, Any]:
    """Get metadata for a Drive file."""
    return service.files().get(fileId=file_id, fields="id,name,mimeType").execute()


def export_file_text(service: Any, file_id: str, mime_type: str) -> str:
    """Export a Google Workspace file as plain text."""
    export_info = _EXPORT_MAP.get(mime_type)
    if not export_info:
        logger.warning("No export mapping for MIME type: %s", mime_type)
        return ""

    export_mime, file_type = export_info
    content = service.files().export(fileId=file_id, mimeType=export_mime).execute()

    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)

    logger.info("Exported %d chars from Drive file %s (type=%s)", len(text), file_id, file_type)
    return text.strip()


def get_drive_file_type(mime_type: str) -> str | None:
    """Map Google MIME type to our file_type classification."""
    info = _EXPORT_MAP.get(mime_type)
    return info[1] if info else None
