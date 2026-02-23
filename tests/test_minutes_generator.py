"""Tests for minutes generator prompt building."""

from minutes.generator import build_minutes_prompt


def test_build_minutes_prompt_basic() -> None:
    meeting = {
        "title": "Sprint Planning",
        "start_time": "2025-01-01T10:00:00",
        "end_time": "2025-01-01T11:00:00",
        "description": "Q1 planning session",
    }
    entries = [
        {"speaker": "Alice", "text": "Let's start", "timestamp": "2025-01-01T10:00:00", "response_category": None},
        {
            "speaker": "Bot",
            "text": "[ANSWERED] Yes",
            "timestamp": "2025-01-01T10:00:05",
            "response_category": "answered",
        },
    ]
    prompt = build_minutes_prompt(meeting, entries)
    assert "Sprint Planning" in prompt
    assert "Alice: Let's start" in prompt
    assert "[ANSWERED]" in prompt
    assert "Q1 planning session" in prompt


def test_build_minutes_prompt_no_description() -> None:
    meeting = {
        "title": "Quick Sync",
        "start_time": "2025-01-01T10:00:00",
        "end_time": "2025-01-01T10:15:00",
        "description": "",
    }
    entries = [
        {"speaker": "Bob", "text": "Hello", "timestamp": "2025-01-01T10:00:00", "response_category": None},
    ]
    prompt = build_minutes_prompt(meeting, entries)
    assert "Quick Sync" in prompt
    assert "Bob: Hello" in prompt
