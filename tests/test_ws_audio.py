"""Tests for bot/ws_audio.py — WebSocket audio bridge."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import bot.router as router_mod
import bot.ws_audio as ws_audio_mod
from config import settings
from main import app


def _set_ws_test_settings() -> None:
    settings.api_key = None
    settings.recall_api_key = "test-recall-key"
    settings.recall_base_url = "https://test.recall.ai/api/v1"
    settings.webhook_base_url = "https://my-server.example.com"
    settings.gemini_live_enabled = False
    settings.gemini_live_output_sample_rate = 24000


def test_ws_audio_rejects_when_no_live_manager() -> None:
    _set_ws_test_settings()
    old_manager = ws_audio_mod._live_manager
    ws_audio_mod._live_manager = None

    from bot.ws_audio import router as ws_router

    app.include_router(ws_router, prefix="/bot")

    try:
        client = TestClient(app)
        with contextlib.suppress(Exception), client.websocket_connect("/bot/ws/audio"):
            pass  # Server should close the connection
    finally:
        ws_audio_mod._live_manager = old_manager


def test_ws_audio_rejects_when_no_session() -> None:
    _set_ws_test_settings()

    mock_manager = MagicMock()
    mock_manager.get_session.return_value = None

    old_manager = ws_audio_mod._live_manager
    ws_audio_mod._live_manager = mock_manager

    try:
        client = TestClient(app)
        with contextlib.suppress(Exception), client.websocket_connect("/bot/ws/audio"):
            pass  # Server should close the connection
    finally:
        ws_audio_mod._live_manager = old_manager


def test_set_live_manager() -> None:
    _set_ws_test_settings()

    old_manager = ws_audio_mod._live_manager
    try:
        mock_manager = MagicMock()
        ws_audio_mod.set_live_manager(mock_manager)
        assert ws_audio_mod._live_manager is mock_manager

        ws_audio_mod.set_live_manager(None)
        assert ws_audio_mod._live_manager is None
    finally:
        ws_audio_mod._live_manager = old_manager


# --- Integration: webhook skips text pipeline during live session ---


def test_webhook_returns_received_live_when_live_session_active() -> None:
    _set_ws_test_settings()

    mock_manager = MagicMock()
    mock_manager.has_session.return_value = True

    old_live = router_mod._live_manager
    router_mod._live_manager = mock_manager

    try:
        client = TestClient(app)
        payload = {
            "data": {
                "bot": {"id": "bot-live-1"},
                "data": {
                    "words": [{"text": "Hello from live mode"}],
                    "participant": {"name": "Speaker"},
                },
            }
        }
        resp = client.post("/bot/webhook/transcript", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "received_live"
        assert data["speaker"] == "Speaker"
    finally:
        router_mod._live_manager = old_live


# --- _classify_by_content ---


def test_classify_by_content_answered() -> None:
    from bot.ws_audio import _classify_by_content

    assert _classify_by_content("売上は前年比120%です。") == "answered"
    assert _classify_by_content("この機能はPython 3.9以上で動作します。") == "answered"


def test_classify_by_content_taken_back() -> None:
    from bot.ws_audio import _classify_by_content

    assert _classify_by_content("持ち帰って本人に確認します。") == "taken_back"
    assert _classify_by_content("その件は検討して後日回答します。") == "taken_back"
    assert _classify_by_content("確認して折り返します。") == "taken_back"


def test_classify_by_content_empty() -> None:
    from bot.ws_audio import _classify_by_content

    assert _classify_by_content("") is None
    assert _classify_by_content("abc") is None


def test_compute_mute_seconds_bounds() -> None:
    from bot.ws_audio import _compute_mute_seconds

    assert _compute_mute_seconds(0.0) == 0.5
    assert _compute_mute_seconds(-1.0) == 0.5
    assert _compute_mute_seconds(1.0) == 1.6
    assert _compute_mute_seconds(20.0) == 12.0


def test_webhook_falls_through_when_live_not_active() -> None:
    _set_ws_test_settings()

    mock_manager = MagicMock()
    mock_manager.has_session.return_value = False

    old_live = router_mod._live_manager
    router_mod._live_manager = mock_manager

    try:
        client = TestClient(app)
        payload = {
            "data": {
                "bot": {"id": "bot-normal-1"},
                "data": {
                    "words": [{"text": "Normal transcript"}],
                    "participant": {"name": "Alice"},
                },
            }
        }
        resp = client.post("/bot/webhook/transcript", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "received"
    finally:
        router_mod._live_manager = old_live
