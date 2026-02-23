"""Google Calendar API wrapper for fetching events and extracting Meet URLs."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

logger = logging.getLogger("meeting-proxy.calendar")

_MEET_URL_PATTERN = re.compile(r"https://meet\.google\.com/[a-z\-]+")


def build_calendar_service(credentials: Any) -> Any:
    """Build a Google Calendar API service."""
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def fetch_upcoming_events(
    service: Any,
    calendar_id: str = "primary",
    days_ahead: int = 7,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Fetch upcoming events from Google Calendar."""
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = result.get("items", [])
    return [_normalize_event(e, calendar_id) for e in events]


def _normalize_event(event: dict[str, Any], calendar_id: str) -> dict[str, Any]:
    """Convert a Google Calendar event to our meeting model format."""
    start = event.get("start", {})
    end = event.get("end", {})

    meeting_url = _extract_meet_url(event)

    return {
        "id": event["id"],
        "title": event.get("summary", "(無題)"),
        "description": event.get("description", ""),
        "start_time": start.get("dateTime", start.get("date", "")),
        "end_time": end.get("dateTime", end.get("date", "")),
        "meeting_url": meeting_url,
        "calendar_id": calendar_id,
        "ai_enabled": 0,
        "bot_id": None,
        "bot_status": "idle",
    }


def _extract_meet_url(event: dict[str, Any]) -> str | None:
    """Extract a Google Meet URL from the event."""
    # Check conferenceData first
    conf = event.get("conferenceData", {})
    for ep in conf.get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            uri = ep.get("uri", "")
            if "meet.google.com" in uri:
                return uri

    # Check hangoutLink
    hangout = event.get("hangoutLink", "")
    if "meet.google.com" in hangout:
        return hangout

    # Scan description for Meet URL
    desc = event.get("description", "") or ""
    match = _MEET_URL_PATTERN.search(desc)
    if match:
        return match.group(0)

    return None
