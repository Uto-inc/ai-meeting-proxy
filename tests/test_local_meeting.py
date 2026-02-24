"""Tests for bot.local_meeting.LocalMeetingSession."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import settings


def _set_default_test_settings() -> None:
    settings.meeting_mode = "local"
    settings.gemini_live_enabled = True
    settings.gemini_live_output_sample_rate = 24000
    settings.blackhole_capture_device = "BlackHole 2ch"
    settings.blackhole_playback_device = "BlackHole 16ch"
    settings.local_audio_sample_rate = 16000
    settings.local_audio_chunk_ms = 100
    settings.bot_display_name = "Test Bot"
    settings.api_key = None


@pytest.mark.asyncio
async def test_local_session_start_stop() -> None:
    """LocalMeetingSession initializes all components and cleans up on stop."""
    _set_default_test_settings()

    mock_browser = AsyncMock()
    mock_browser.join_meeting = AsyncMock()
    mock_browser.leave_meeting = AsyncMock()

    mock_live_manager = AsyncMock()
    mock_gemini_session = AsyncMock()
    mock_live_manager.create_session = AsyncMock(return_value=mock_gemini_session)
    mock_live_manager.has_session = MagicMock(return_value=True)
    mock_live_manager.remove_session = AsyncMock()

    mock_repo = AsyncMock()
    mock_repo.update_bot_status = AsyncMock()

    with patch("bot.audio_bridge.AudioBridge") as mock_bridge_cls:
        mock_bridge = AsyncMock()
        mock_bridge.start = AsyncMock()
        mock_bridge.stop = AsyncMock()
        mock_bridge_cls.return_value = mock_bridge

        from bot.local_meeting import LocalMeetingSession

        session = LocalMeetingSession(
            bot_id="bot-123",
            meeting_url="https://meet.google.com/abc-defg-hij",
            bot_name="Test Bot",
            browser=mock_browser,
            live_manager=mock_live_manager,
            repo=mock_repo,
            meeting_id="meeting-456",
        )

        await session.start("You are a meeting assistant.")

        # Verify all components initialized
        mock_browser.join_meeting.assert_awaited_once_with("https://meet.google.com/abc-defg-hij", "Test Bot")
        mock_live_manager.create_session.assert_awaited_once()
        mock_bridge.start.assert_awaited_once()

        # Stop session
        await session.stop()

        # Verify cleanup
        mock_bridge.stop.assert_awaited_once()
        mock_browser.leave_meeting.assert_awaited_once_with("bot-123")
        mock_live_manager.remove_session.assert_awaited_once_with("bot-123")
        mock_repo.update_bot_status.assert_awaited_with("meeting-456", "bot-123", "left")


@pytest.mark.asyncio
async def test_handle_turn_plays_audio() -> None:
    """Gemini turn response is played through the audio bridge."""
    _set_default_test_settings()

    mock_browser = AsyncMock()
    mock_live_manager = AsyncMock()
    mock_gemini_session = MagicMock()
    mock_gemini_session.set_mute_duration = MagicMock()

    mock_bridge = MagicMock()
    mock_bridge.play_audio = MagicMock()

    mock_repo = AsyncMock()
    mock_repo.add_conversation_entry = AsyncMock()

    from bot.local_meeting import LocalMeetingSession

    session = LocalMeetingSession(
        bot_id="bot-123",
        meeting_url="https://meet.google.com/abc",
        bot_name="Test Bot",
        browser=mock_browser,
        live_manager=mock_live_manager,
        repo=mock_repo,
        meeting_id="meeting-456",
    )
    session._audio_bridge = mock_bridge
    session._gemini_session = mock_gemini_session

    # Simulate Gemini turn with audio (48000 bytes = 1 second at 24kHz 16-bit mono)
    audio_data = b"\x00" * 48000
    text_data = "テスト応答です"

    await session._handle_turn(audio_data, text_data)

    # Verify audio was played
    mock_bridge.play_audio.assert_called_once_with(audio_data, settings.gemini_live_output_sample_rate)

    # Verify echo suppression
    assert mock_gemini_session.set_mute_duration.call_count == 2  # pre-mute + post-mute

    # Verify response was persisted
    mock_repo.add_conversation_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_turn_no_audio() -> None:
    """Turn with no audio but text still persists the response."""
    _set_default_test_settings()

    mock_repo = AsyncMock()
    mock_repo.add_conversation_entry = AsyncMock()

    from bot.local_meeting import LocalMeetingSession

    session = LocalMeetingSession(
        bot_id="bot-123",
        meeting_url="https://meet.google.com/abc",
        bot_name="Test Bot",
        browser=AsyncMock(),
        live_manager=AsyncMock(),
        repo=mock_repo,
        meeting_id="meeting-456",
    )
    session._audio_bridge = MagicMock()

    await session._handle_turn(b"", "テキストのみ")

    # Audio should not be played for empty audio
    session._audio_bridge.play_audio.assert_not_called()

    # But text should still be persisted
    mock_repo.add_conversation_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_classify_by_content() -> None:
    """Content-based classification works for local meeting responses."""
    from bot.local_meeting import _classify_by_content

    assert _classify_by_content("持ち帰って検討します") == "taken_back"
    assert _classify_by_content("はい、その通りです") == "answered"
    assert _classify_by_content("") is None
    assert _classify_by_content("abc") is None
