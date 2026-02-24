"""WebSocket audio bridge between Recall.ai and Gemini Live API."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from bot.audio_utils import decode_b64_pcm, pcm_to_mp3_b64
from bot.meeting_conversation import MeetingConversationSession
from config import settings

logger = logging.getLogger("meeting-proxy.ws-audio")

router = APIRouter(tags=["bot"])

# Module-level reference set by main.py during startup
_live_manager: Any = None


def set_live_manager(manager: Any) -> None:
    """Set the module-level GeminiLiveManager reference."""
    global _live_manager
    _live_manager = manager


@router.websocket("/ws/audio")
async def ws_audio_bridge(websocket: WebSocket) -> None:
    """WebSocket endpoint for Recall.ai audio_mixed_raw streaming.

    Bot ID is extracted from the first incoming message's bot.id field.
    Receives PCM audio from Recall.ai, forwards to Gemini Live API,
    and sends back audio responses via Recall.ai output_audio API.
    """
    await websocket.accept()
    logger.info("WebSocket connected (awaiting bot identification)")

    if _live_manager is None:
        logger.error("GeminiLiveManager not initialized, closing WebSocket")
        await websocket.close(code=1011, reason="Live manager not initialized")
        return

    bot_id: str | None = None
    session: Any = None
    sender_task: asyncio.Task[None] | None = None
    original_on_turn_complete: Any = None
    audio_chunk_count = 0

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from WebSocket")
                continue

            # Extract bot_id from message on first message
            if bot_id is None:
                msg_bot = message.get("data", {}).get("bot", {})
                bot_id = msg_bot.get("id", "")
                if not bot_id:
                    # Try top-level bot field
                    bot_id = message.get("bot", {}).get("id", "")
                if bot_id:
                    session = _live_manager.get_session(bot_id)
                    if session is None:
                        logger.error("No Gemini Live session for bot %s, closing", bot_id)
                        await websocket.close(code=1011, reason="No live session for bot")
                        return
                    logger.info("WebSocket identified bot %s, starting audio bridge", bot_id)
                    # Start the sender task now that we have a session
                    pending_sends: asyncio.Queue[tuple[bytes, str]] = asyncio.Queue()
                    original_on_turn_complete = session._on_turn_complete
                    _queue = pending_sends  # bind for closure

                    async def _on_turn_complete_wrapper(
                        audio_data: bytes,
                        text_data: str,
                        q: asyncio.Queue = _queue,  # type: ignore[type-arg]
                    ) -> None:
                        await q.put((audio_data, text_data))

                    session._on_turn_complete = _on_turn_complete_wrapper
                    sender_task = asyncio.create_task(_send_audio_responses(bot_id, pending_sends, websocket.app))
                else:
                    logger.debug("Message without bot_id, skipping")
                    continue

            event = message.get("event")
            if session is None:
                logger.debug("Pre-session message: event=%s keys=%s", event, list(message.get("data", {}).keys()))

            if event == "audio_mixed_raw.data":
                data = message.get("data", {})
                inner = data.get("data", {})
                # Recall.ai sends audio as {"buffer": "<base64>"} inside data.data
                if isinstance(inner, dict):
                    b64_audio = inner.get("buffer", "") or inner.get("data", "")
                else:
                    b64_audio = inner if isinstance(inner, str) else ""
                if b64_audio and isinstance(b64_audio, str) and session is not None:
                    try:
                        pcm_bytes = decode_b64_pcm(b64_audio)
                    except Exception:
                        logger.warning(
                            "Failed to decode audio chunk from Recall.ai (bot=%s, event=%s)",
                            bot_id,
                            event,
                            exc_info=True,
                        )
                        continue
                    audio_chunk_count += 1
                    if audio_chunk_count == 1:
                        logger.info(
                            "First audio chunk from Recall.ai (bot=%s, %d bytes PCM)",
                            bot_id,
                            len(pcm_bytes),
                        )
                    elif audio_chunk_count % 100 == 0:
                        logger.info(
                            "Audio bridge stats (bot=%s): %d chunks forwarded to Gemini",
                            bot_id,
                            audio_chunk_count,
                        )
                    await session.send_audio(pcm_bytes)

            elif event in ("participant_events.speech_on", "participant_events.speech_off"):
                participant = message.get("data", {}).get("participant", {})
                logger.debug(
                    "Speech event: %s participant=%s (bot=%s)",
                    event,
                    participant.get("name", "unknown"),
                    bot_id,
                )
            else:
                logger.debug("Unhandled WebSocket event: %s (bot=%s)", event, bot_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for bot %s (total audio chunks: %d)", bot_id, audio_chunk_count)
    except Exception:
        logger.exception("WebSocket error for bot %s", bot_id)
    finally:
        if session is not None and sender_task is not None:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task
            if original_on_turn_complete is not None:
                session._on_turn_complete = original_on_turn_complete
        logger.info("WebSocket cleanup complete for bot %s", bot_id)


async def _send_audio_responses(bot_id: str, pending_sends: asyncio.Queue[tuple[bytes, str]], app: Any) -> None:
    """Process queued turn-complete events and send audio to Recall.ai."""
    from bot.recall_client import RecallClient

    while True:
        try:
            audio_data, text_data = await pending_sends.get()
        except asyncio.CancelledError:
            break

        if not audio_data:
            logger.info(
                "Empty audio turn for bot %s, text=%s",
                bot_id,
                text_data[:80] if text_data else "(none)",
            )
            continue

        try:
            playback_seconds = len(audio_data) / (settings.gemini_live_output_sample_rate * 2)
            mute_seconds = _compute_mute_seconds(playback_seconds)
            session = _live_manager.get_session(bot_id) if _live_manager else None
            if session is not None:
                # Apply a short pre-mute to avoid a race where bot audio echoes
                # back into Gemini before output_audio API call completes.
                session.set_mute_duration(0.5)

            b64_mp3 = pcm_to_mp3_b64(audio_data, sample_rate=settings.gemini_live_output_sample_rate)
            client = RecallClient()
            await client.send_audio(bot_id, b64_mp3)

            if session is not None:
                session.set_mute_duration(mute_seconds)

            logger.info(
                "Live audio response sent to bot %s (%d bytes PCM, %.1fs, mute=%.1fs)",
                bot_id,
                len(audio_data),
                playback_seconds,
                mute_seconds,
            )
        except Exception:
            logger.exception("Failed to send audio response to Recall.ai (bot=%s)", bot_id)

        if text_data:
            try:
                await _persist_bot_response(bot_id, text_data, app)
            except Exception:
                logger.exception("Failed to persist bot response (bot=%s)", bot_id)


_TAKEN_BACK_PATTERN = re.compile(r"持ち帰|確認して|検討し|後日|本人に確認")


def _compute_mute_seconds(playback_seconds: float) -> float:
    """Compute bounded echo-suppression mute duration."""
    if playback_seconds <= 0:
        return 0.5
    # Keep a small tail margin, but avoid excessively long mute windows.
    return min(max(playback_seconds + 0.6, 0.5), 12.0)


def _classify_by_content(text: str) -> str | None:
    """Fallback classification based on response content when tags are absent.

    Returns 'taken_back', 'answered', or None (if text is too short/empty).
    """
    if not text or len(text.strip()) < 5:
        return None
    if _TAKEN_BACK_PATTERN.search(text):
        return "taken_back"
    return "answered"


async def _persist_bot_response(bot_id: str, text: str, app: Any) -> None:
    """Classify and persist bot's text response to the database."""
    from bot.router import _bot_meeting_map

    clean_text, category = MeetingConversationSession.classify_response(text)
    if category is None:
        category = _classify_by_content(clean_text)

    meeting_id = _bot_meeting_map.get(bot_id)
    repo = getattr(getattr(app, "state", None), "repo", None)
    if not repo or not meeting_id:
        return

    await repo.add_conversation_entry(meeting_id, bot_id, settings.bot_display_name, clean_text, "bot", category)
    logger.info("Live bot response persisted [%s]: %s", category or "none", clean_text[:120])
