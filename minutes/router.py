"""Minutes generation and export API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from auth.google_oauth import credentials_from_token_row, refresh_if_needed, token_expiry_iso

logger = logging.getLogger("meeting-proxy.minutes")

router = APIRouter(tags=["minutes"])


def _get_repo(request: Request) -> Any:
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return repo


@router.post("/meetings/{meeting_id}/minutes/generate")
async def generate_minutes(request: Request, meeting_id: str) -> JSONResponse:
    """Generate meeting minutes from conversation log using Gemini."""
    repo = _get_repo(request)

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    entries = await repo.get_conversation_log(meeting_id)
    if not entries:
        raise HTTPException(status_code=400, detail="No conversation log found for this meeting")

    from minutes.generator import build_minutes_prompt
    from minutes.generator import generate_minutes as gen

    prompt = build_minutes_prompt(meeting, entries)
    result = await run_in_threadpool(gen, prompt)

    minutes_data = {
        "meeting_id": meeting_id,
        "summary": result.get("summary", ""),
        "answered_items": result.get("answered_items", []),
        "taken_back_items": result.get("taken_back_items", []),
        "action_items": result.get("action_items", []),
        "full_markdown": result.get("full_markdown", ""),
        "status": "draft",
    }
    minutes_id = await repo.save_minutes(minutes_data)

    logger.info("Minutes generated for meeting %s (id=%d)", meeting_id, minutes_id)
    return JSONResponse({"id": minutes_id, **result})


@router.get("/meetings/{meeting_id}/minutes")
async def get_minutes(request: Request, meeting_id: str) -> JSONResponse:
    """Get the latest minutes for a meeting."""
    repo = _get_repo(request)
    minutes = await repo.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=404, detail="No minutes found for this meeting")
    return JSONResponse(minutes)


@router.put("/meetings/{meeting_id}/minutes")
async def update_minutes(request: Request, meeting_id: str) -> JSONResponse:
    """Update meeting minutes (edit summary, items, etc.)."""
    repo = _get_repo(request)
    body = await request.json()

    allowed_fields = {"summary", "answered_items", "taken_back_items", "action_items", "full_markdown", "status"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    updated = await repo.update_minutes(meeting_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="No minutes found for this meeting")

    logger.info("Minutes updated for meeting %s", meeting_id)
    return JSONResponse({"detail": "Minutes updated", "meeting_id": meeting_id})


@router.post("/meetings/{meeting_id}/minutes/export")
async def export_to_google_docs(request: Request, meeting_id: str) -> JSONResponse:
    """Export meeting minutes to Google Docs."""
    repo = _get_repo(request)

    minutes = await repo.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=404, detail="No minutes found. Generate minutes first.")

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    token_row = await repo.get_token()
    if not token_row:
        raise HTTPException(status_code=401, detail="Google account not linked")

    creds = credentials_from_token_row(token_row)
    refreshed, creds = refresh_if_needed(creds)
    if refreshed:
        await repo.update_token("default", creds.token, token_expiry_iso(creds))

    from minutes.docs_exporter import create_minutes_doc

    title = f"議事録: {meeting.get('title', meeting_id)}"
    markdown = minutes.get("full_markdown", "")

    result = await run_in_threadpool(create_minutes_doc, creds, title, markdown)

    await repo.set_minutes_export(meeting_id, result["doc_id"], result["doc_url"])

    logger.info("Minutes exported to Google Docs: %s", result["doc_url"])
    return JSONResponse(
        {
            "google_doc_id": result["doc_id"],
            "google_doc_url": result["doc_url"],
        }
    )
