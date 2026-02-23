"""Tests for bot/gemini_live.py — Gemini Live API session management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import settings


def _set_default_test_settings() -> None:
    settings.gcp_project_id = "local-test"
    settings.gcp_location = "us-central1"
    settings.gemini_live_model = "gemini-live-2.5-flash-native-audio"
    settings.gemini_live_session_timeout_seconds = 840
    settings.gemini_live_output_sample_rate = 24000


def _make_mock_async_iter() -> AsyncMock:
    """Create a mock async iterable that immediately stops."""
    mock = AsyncMock()
    mock.__aiter__ = lambda s: s
    mock.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
    return mock


def _make_mock_client(mock_session: AsyncMock) -> MagicMock:
    """Create a mock genai.Client whose aio.live.connect returns an async context manager."""

    @asynccontextmanager
    async def _connect(**kwargs):  # type: ignore[no-untyped-def]
        yield mock_session

    mock_client = MagicMock()
    mock_client.aio.live.connect = _connect
    return mock_client


# --- GeminiLiveSession ---


@pytest.mark.asyncio
async def test_session_connect_and_disconnect() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveSession

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_make_mock_async_iter())

    mock_client = _make_mock_client(mock_session)

    with patch("bot.gemini_live.genai.Client", return_value=mock_client):
        session = GeminiLiveSession(
            bot_id="test-bot",
            system_instruction="Test instruction",
            on_audio_chunk=lambda d: None,
            on_turn_complete=lambda a, t: None,
            on_text_chunk=lambda t: None,
        )
        await session.connect()

    assert session.connected is True

    await session.disconnect()
    assert session.connected is False


@pytest.mark.asyncio
async def test_session_send_audio_when_not_connected() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveSession

    session = GeminiLiveSession(
        bot_id="test-bot",
        system_instruction="Test",
        on_audio_chunk=lambda d: None,
        on_turn_complete=lambda a, t: None,
        on_text_chunk=lambda t: None,
    )
    # Should not raise
    await session.send_audio(b"\x00\x00")


@pytest.mark.asyncio
async def test_session_send_audio_forwards_to_gemini() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveSession

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_make_mock_async_iter())
    mock_session.send_realtime_input = AsyncMock()

    mock_client = _make_mock_client(mock_session)

    with patch("bot.gemini_live.genai.Client", return_value=mock_client):
        session = GeminiLiveSession(
            bot_id="test-bot",
            system_instruction="Test",
            on_audio_chunk=lambda d: None,
            on_turn_complete=lambda a, t: None,
            on_text_chunk=lambda t: None,
        )
        await session.connect()
        await session.send_audio(b"\x00\x01\x02\x03")

    mock_session.send_realtime_input.assert_awaited_once()


# --- GeminiLiveManager ---


@pytest.mark.asyncio
async def test_manager_create_and_remove_session() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveManager

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_make_mock_async_iter())

    mock_client = _make_mock_client(mock_session)

    manager = GeminiLiveManager()

    with patch("bot.gemini_live.genai.Client", return_value=mock_client):
        session = await manager.create_session(
            bot_id="bot-1",
            system_instruction="Test",
            on_audio_chunk=lambda d: None,
            on_turn_complete=lambda a, t: None,
            on_text_chunk=lambda t: None,
        )

    assert manager.has_session("bot-1") is True
    assert manager.get_session("bot-1") is session

    await manager.remove_session("bot-1")
    assert manager.has_session("bot-1") is False
    assert manager.get_session("bot-1") is None


@pytest.mark.asyncio
async def test_manager_get_nonexistent_session() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveManager

    manager = GeminiLiveManager()
    assert manager.get_session("nonexistent") is None
    assert manager.has_session("nonexistent") is False


@pytest.mark.asyncio
async def test_manager_shutdown_cleans_all() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveManager

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_make_mock_async_iter())

    mock_client = _make_mock_client(mock_session)

    manager = GeminiLiveManager()

    with patch("bot.gemini_live.genai.Client", return_value=mock_client):
        await manager.create_session(
            "bot-1",
            "Test",
            lambda d: None,
            lambda a, t: None,
            lambda t: None,
        )
        await manager.create_session(
            "bot-2",
            "Test",
            lambda d: None,
            lambda a, t: None,
            lambda t: None,
        )

    assert manager.has_session("bot-1")
    assert manager.has_session("bot-2")

    await manager.shutdown()
    assert not manager.has_session("bot-1")
    assert not manager.has_session("bot-2")


@pytest.mark.asyncio
async def test_manager_create_replaces_existing() -> None:
    _set_default_test_settings()
    from bot.gemini_live import GeminiLiveManager

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_make_mock_async_iter())

    mock_client = _make_mock_client(mock_session)

    manager = GeminiLiveManager()

    with patch("bot.gemini_live.genai.Client", return_value=mock_client):
        session1 = await manager.create_session(
            "bot-1",
            "V1",
            lambda d: None,
            lambda a, t: None,
            lambda t: None,
        )
        session2 = await manager.create_session(
            "bot-1",
            "V2",
            lambda d: None,
            lambda a, t: None,
            lambda t: None,
        )

    assert manager.get_session("bot-1") is session2
    assert session1 is not session2

    await manager.shutdown()
