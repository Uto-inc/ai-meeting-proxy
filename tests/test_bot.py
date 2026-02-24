from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from config import settings
from main import app


def _set_bot_test_settings() -> None:
    settings.api_key = None
    settings.meeting_mode = "recall"
    settings.recall_api_key = "test-recall-key"
    settings.recall_base_url = "https://test.recall.ai/api/v1"
    settings.webhook_base_url = "https://my-server.example.com"


def _clear_recall_settings() -> None:
    settings.api_key = None
    settings.meeting_mode = "recall"
    settings.recall_api_key = None


# --- /bot/join ---


def test_join_returns_bot_id() -> None:
    _set_bot_test_settings()
    client = TestClient(app)
    mock_response = {"id": "bot-abc-123", "status_changes": [{"code": "ready"}]}

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.create_bot.return_value = mock_response
        mock_get.return_value = mock_client

        resp = client.post("/bot/join", json={"meeting_url": "https://meet.google.com/abc-defg-hij"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_id"] == "bot-abc-123"


def test_join_missing_url_returns_400() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    resp = client.post("/bot/join", json={})
    assert resp.status_code == 400
    assert "meeting_url" in resp.json()["detail"]


def test_join_returns_503_when_not_configured() -> None:
    _clear_recall_settings()
    client = TestClient(app)

    resp = client.post("/bot/join", json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert resp.status_code == 503


# --- /bot/{bot_id}/status ---


def test_status_returns_bot_info() -> None:
    _set_bot_test_settings()
    client = TestClient(app)
    mock_response = {"id": "bot-abc-123", "status_changes": [{"code": "in_call_recording"}]}

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.get_bot_status.return_value = mock_response
        mock_get.return_value = mock_client

        resp = client.get("/bot/bot-abc-123/status")

    assert resp.status_code == 200
    assert resp.json()["bot_id"] == "bot-abc-123"


# --- /bot/{bot_id}/leave ---


def test_leave_sends_request() -> None:
    _set_bot_test_settings()
    client = TestClient(app)
    mock_response = {}

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.leave_meeting.return_value = mock_response
        mock_get.return_value = mock_client

        resp = client.post("/bot/bot-abc-123/leave")

    assert resp.status_code == 200
    assert resp.json()["detail"] == "Leave request sent"


# --- /bot/webhook/transcript ---


def test_webhook_receives_transcript() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    payload = {
        "data": {
            "bot": {"id": "bot-test-1"},
            "data": {
                "words": [{"text": "Hello everyone, let's get started."}],
                "participant": {"name": "Alice"},
            },
        }
    }
    resp = client.post("/bot/webhook/transcript", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "received"
    assert data["speaker"] == "Alice"


def test_webhook_ignores_empty_transcript() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    payload = {
        "data": {
            "bot": {"id": "bot-test-1"},
            "data": {
                "words": [{"text": "  "}],
                "participant": {"name": "Bob"},
            },
        }
    }
    resp = client.post("/bot/webhook/transcript", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


# --- Avatar mode ---


def test_join_with_avatar_enabled() -> None:
    _set_bot_test_settings()
    client = TestClient(app)
    mock_response = {"id": "bot-avatar-1", "status_changes": [{"code": "ready"}]}

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.create_bot_with_audio.return_value = mock_response
        mock_get.return_value = mock_client

        resp = client.post(
            "/bot/join",
            json={
                "meeting_url": "https://meet.google.com/abc-defg-hij",
                "enable_avatar": True,
                "bot_name": "TestAvatar",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_id"] == "bot-avatar-1"
    assert data["avatar_enabled"] is True


def test_join_without_avatar_uses_create_bot() -> None:
    _set_bot_test_settings()
    client = TestClient(app)
    mock_response = {"id": "bot-normal-1", "status_changes": [{"code": "ready"}]}

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.create_bot.return_value = mock_response
        mock_get.return_value = mock_client

        resp = client.post(
            "/bot/join",
            json={
                "meeting_url": "https://meet.google.com/abc-defg-hij",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["avatar_enabled"] is False


def test_leave_cleans_up_conversation_session() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    with patch("bot.router._get_recall_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.leave_meeting.return_value = {}
        mock_get.return_value = mock_client

        resp = client.post("/bot/bot-abc-123/leave")

    assert resp.status_code == 200
    assert resp.json()["detail"] == "Leave request sent"


def test_webhook_with_bot_id_triggers_avatar() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    payload = {
        "data": {
            "bot": {"id": "bot-avatar-1"},
            "data": {
                "words": [{"text": "これについてどう思いますか？"}],
                "participant": {"name": "Alice"},
            },
        }
    }
    resp = client.post("/bot/webhook/transcript", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


def test_webhook_without_bot_id_still_works() -> None:
    _set_bot_test_settings()
    client = TestClient(app)

    payload = {
        "data": {
            "bot": {},
            "data": {
                "words": [{"text": "Hello everyone."}],
                "participant": {"name": "Bob"},
            },
        }
    }
    resp = client.post("/bot/webhook/transcript", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
