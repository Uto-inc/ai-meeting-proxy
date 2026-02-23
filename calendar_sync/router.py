"""Calendar sync API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from auth.google_oauth import credentials_from_token_row, refresh_if_needed, token_expiry_iso
from calendar_sync.google_calendar import build_calendar_service, fetch_upcoming_events

logger = logging.getLogger("meeting-proxy.calendar")

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _get_credentials(request: Request) -> Any:
    """Retrieve and refresh Google OAuth credentials."""
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    token_row = await repo.get_token()
    if not token_row:
        raise HTTPException(status_code=401, detail="Google account not linked. Visit /auth/google/login")

    creds = credentials_from_token_row(token_row)
    refreshed, creds = refresh_if_needed(creds)
    if refreshed:
        await repo.update_token("default", creds.token, token_expiry_iso(creds))
    return creds


@router.get("/events")
async def list_events(
    request: Request,
    days_ahead: int = Query(default=7, ge=1, le=30),
    calendar_id: str = Query(default="primary"),
) -> JSONResponse:
    """Fetch upcoming events from Google Calendar and sync to local DB."""
    creds = await _get_credentials(request)
    service = build_calendar_service(creds)
    events = await run_in_threadpool(fetch_upcoming_events, service, calendar_id, days_ahead)

    repo = request.app.state.repo
    for event in events:
        existing = await repo.get_meeting(event["id"])
        if existing:
            event["ai_enabled"] = existing["ai_enabled"]
            event["bot_id"] = existing["bot_id"]
            event["bot_status"] = existing["bot_status"]
        await repo.upsert_meeting(event)

    return JSONResponse({"events": events, "count": len(events)})


@router.post("/events/{event_id}/enable-ai")
async def enable_ai(request: Request, event_id: str) -> JSONResponse:
    """Enable AI attendance for a meeting."""
    repo = request.app.state.repo
    meeting = await repo.get_meeting(event_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found. Sync calendar first.")
    if not meeting.get("meeting_url"):
        raise HTTPException(status_code=400, detail="No Google Meet URL found for this event")

    await repo.set_ai_enabled(event_id, True)
    logger.info("AI enabled for meeting %s: %s", event_id, meeting["title"])
    return JSONResponse({"event_id": event_id, "ai_enabled": True, "title": meeting["title"]})


@router.post("/events/{event_id}/disable-ai")
async def disable_ai(request: Request, event_id: str) -> JSONResponse:
    """Disable AI attendance for a meeting."""
    repo = request.app.state.repo
    updated = await repo.set_ai_enabled(event_id, False)
    if not updated:
        raise HTTPException(status_code=404, detail="Meeting not found")
    logger.info("AI disabled for meeting %s", event_id)
    return JSONResponse({"event_id": event_id, "ai_enabled": False})


@router.post("/sync")
async def force_sync(
    request: Request,
    days_ahead: int = Query(default=7, ge=1, le=30),
) -> JSONResponse:
    """Force re-sync calendar events."""
    creds = await _get_credentials(request)
    service = build_calendar_service(creds)
    events = await run_in_threadpool(fetch_upcoming_events, service, "primary", days_ahead)

    repo = request.app.state.repo
    synced = 0
    for event in events:
        existing = await repo.get_meeting(event["id"])
        if existing:
            event["ai_enabled"] = existing["ai_enabled"]
            event["bot_id"] = existing["bot_id"]
            event["bot_status"] = existing["bot_status"]
        await repo.upsert_meeting(event)
        synced += 1

    logger.info("Calendar force-synced: %d events", synced)
    return JSONResponse({"synced": synced, "days_ahead": days_ahead})
