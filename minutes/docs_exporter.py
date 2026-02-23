"""Google Docs export for meeting minutes."""

import logging
from typing import Any

from googleapiclient.discovery import build

logger = logging.getLogger("meeting-proxy.minutes")


def build_docs_service(credentials: Any) -> Any:
    """Build a Google Docs API service."""
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def create_minutes_doc(
    credentials: Any,
    title: str,
    markdown_content: str,
) -> dict[str, str]:
    """Create a Google Doc with the meeting minutes content.

    Returns dict with 'doc_id' and 'doc_url'.
    """
    docs_service = build_docs_service(credentials)

    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    if markdown_content:
        requests = _markdown_to_docs_requests(markdown_content)
        if requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    logger.info("Created Google Doc: %s (%s)", title, doc_url)

    return {"doc_id": doc_id, "doc_url": doc_url}


def _markdown_to_docs_requests(markdown: str) -> list[dict[str, Any]]:
    """Convert markdown text to Google Docs API insert requests.

    Simplified: inserts the entire text as plain text at index 1.
    Heading formatting is applied via named style for lines starting with #.
    """
    if not markdown.strip():
        return []

    requests: list[dict[str, Any]] = []
    lines = markdown.split("\n")

    # Insert all text first (must be done in reverse for correct indexing)
    full_text = markdown + "\n"
    requests.append(
        {
            "insertText": {
                "location": {"index": 1},
                "text": full_text,
            }
        }
    )

    # Apply heading styles
    current_index = 1
    for line in lines:
        line_len = len(line) + 1  # +1 for newline

        if line.startswith("# "):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": current_index, "endIndex": current_index + line_len},
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "fields": "namedStyleType",
                    }
                }
            )
        elif line.startswith("## "):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": current_index, "endIndex": current_index + line_len},
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                        "fields": "namedStyleType",
                    }
                }
            )
        elif line.startswith("### "):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": current_index, "endIndex": current_index + line_len},
                        "paragraphStyle": {"namedStyleType": "HEADING_3"},
                        "fields": "namedStyleType",
                    }
                }
            )

        current_index += line_len

    return requests
