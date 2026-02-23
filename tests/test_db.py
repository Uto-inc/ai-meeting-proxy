"""Tests for database schema and repository."""

import asyncio
import os
import tempfile

import pytest

from db.repository import Repository
from db.schema import init_db


def _run(coro):
    """Run async function in test context."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def repo():
    """Create a temporary database and repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        async def setup():
            db = await init_db(db_path)
            return Repository(db), db

        r, db = _run(setup())
        yield r
        _run(db.close())


def test_schema_creates_tables(repo: Repository) -> None:
    """Verify all tables are created."""

    async def check():
        cursor = await repo._db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = await cursor.fetchall()
        names = {r["name"] for r in rows}
        assert "meetings" in names
        assert "materials" in names
        assert "conversation_log" in names
        assert "minutes" in names
        assert "oauth_tokens" in names

    _run(check())


def test_save_and_get_token(repo: Repository) -> None:
    async def check():
        await repo.save_token("access123", "refresh456", "2025-01-01T00:00:00", "calendar,drive")
        token = await repo.get_token()
        assert token is not None
        assert token["access_token"] == "access123"
        assert token["refresh_token"] == "refresh456"

    _run(check())


def test_delete_token(repo: Repository) -> None:
    async def check():
        await repo.save_token("a", "r", "2025-01-01T00:00:00", "scope")
        await repo.delete_token()
        token = await repo.get_token()
        assert token is None

    _run(check())


def test_upsert_and_get_meeting(repo: Repository) -> None:
    async def check():
        meeting = {
            "id": "event123",
            "title": "Test Meeting",
            "description": "Desc",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00",
            "meeting_url": "https://meet.google.com/abc",
            "calendar_id": "primary",
            "ai_enabled": 0,
            "bot_id": None,
            "bot_status": "idle",
        }
        await repo.upsert_meeting(meeting)
        result = await repo.get_meeting("event123")
        assert result is not None
        assert result["title"] == "Test Meeting"

    _run(check())


def test_set_ai_enabled(repo: Repository) -> None:
    async def check():
        meeting = {
            "id": "ev1",
            "title": "M",
            "description": "",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00",
            "meeting_url": "url",
            "calendar_id": "primary",
            "ai_enabled": 0,
            "bot_id": None,
            "bot_status": "idle",
        }
        await repo.upsert_meeting(meeting)
        await repo.set_ai_enabled("ev1", True)
        result = await repo.get_meeting("ev1")
        assert result["ai_enabled"] == 1

    _run(check())


def test_add_and_list_materials(repo: Repository) -> None:
    async def check():
        meeting = {
            "id": "ev2",
            "title": "M",
            "description": "",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00",
            "meeting_url": "url",
            "calendar_id": "primary",
            "ai_enabled": 0,
            "bot_id": None,
            "bot_status": "idle",
        }
        await repo.upsert_meeting(meeting)
        mat_id = await repo.add_material(
            {
                "meeting_id": "ev2",
                "source_type": "upload",
                "filename": "test.pdf",
                "mime_type": "application/pdf",
                "drive_file_id": None,
                "drive_file_type": None,
                "extracted_text": "hello world",
                "file_path": "data/materials/test.pdf",
                "status": "extracted",
            }
        )
        assert mat_id > 0
        materials = await repo.list_materials("ev2")
        assert len(materials) == 1
        assert materials[0]["filename"] == "test.pdf"

    _run(check())


def test_conversation_log(repo: Repository) -> None:
    async def check():
        meeting = {
            "id": "ev3",
            "title": "M",
            "description": "",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00",
            "meeting_url": "url",
            "calendar_id": "primary",
            "ai_enabled": 0,
            "bot_id": None,
            "bot_status": "idle",
        }
        await repo.upsert_meeting(meeting)
        await repo.add_conversation_entry("ev3", "bot1", "Alice", "Hello", "human")
        await repo.add_conversation_entry("ev3", "bot1", "Bot", "Hi!", "bot", "answered")
        log = await repo.get_conversation_log("ev3")
        assert len(log) == 2
        assert log[0]["speaker"] == "Alice"
        assert log[1]["response_category"] == "answered"

    _run(check())


def test_save_and_get_minutes(repo: Repository) -> None:
    async def check():
        meeting = {
            "id": "ev4",
            "title": "M",
            "description": "",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00",
            "meeting_url": "url",
            "calendar_id": "primary",
            "ai_enabled": 0,
            "bot_id": None,
            "bot_status": "idle",
        }
        await repo.upsert_meeting(meeting)
        minutes_id = await repo.save_minutes(
            {
                "meeting_id": "ev4",
                "summary": "Test summary",
                "answered_items": [{"q": "Q1", "a": "A1"}],
                "taken_back_items": [],
                "action_items": [{"task": "Do thing", "owner": "Alice"}],
                "full_markdown": "# Minutes",
                "status": "draft",
            }
        )
        assert minutes_id > 0
        result = await repo.get_minutes("ev4")
        assert result is not None
        assert result["summary"] == "Test summary"
        assert isinstance(result["answered_items"], list)

    _run(check())
