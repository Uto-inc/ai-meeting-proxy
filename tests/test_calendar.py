"""Tests for calendar sync module."""

from calendar_sync.google_calendar import _extract_meet_url, _normalize_event


def test_extract_meet_url_from_conference_data() -> None:
    event = {
        "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}]}
    }
    assert _extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_extract_meet_url_from_hangout_link() -> None:
    event = {"hangoutLink": "https://meet.google.com/xyz-uvwx-rst"}
    assert _extract_meet_url(event) == "https://meet.google.com/xyz-uvwx-rst"


def test_extract_meet_url_from_description() -> None:
    event = {"description": "Join at https://meet.google.com/abc-defg-hij please"}
    assert _extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_extract_meet_url_none() -> None:
    event = {"summary": "No Meet link"}
    assert _extract_meet_url(event) is None


def test_normalize_event() -> None:
    event = {
        "id": "ev123",
        "summary": "Team Standup",
        "description": "Daily sync",
        "start": {"dateTime": "2025-01-01T10:00:00+09:00"},
        "end": {"dateTime": "2025-01-01T10:30:00+09:00"},
        "hangoutLink": "https://meet.google.com/aaa-bbbb-ccc",
    }
    result = _normalize_event(event, "primary")
    assert result["id"] == "ev123"
    assert result["title"] == "Team Standup"
    assert result["meeting_url"] == "https://meet.google.com/aaa-bbbb-ccc"
    assert result["ai_enabled"] == 0
    assert result["bot_status"] == "idle"


def test_normalize_event_no_title() -> None:
    event = {
        "id": "ev_no_title",
        "start": {"date": "2025-01-01"},
        "end": {"date": "2025-01-01"},
    }
    result = _normalize_event(event, "primary")
    assert result["title"] == "(無題)"
