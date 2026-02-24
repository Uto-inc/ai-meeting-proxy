"""Gemini Live API session management for real-time audio conversations."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from config import settings

logger = logging.getLogger("meeting-proxy.gemini-live")

AudioChunkCallback = Callable[[bytes], None]
TextChunkCallback = Callable[[str], None]
TurnCompleteCallback = Callable[[bytes, str], Any]


class GeminiLiveSession:
    """Manages a single Gemini Live API session for one bot/meeting.

    Handles connection, audio send/receive, automatic reconnection before
    the 15-minute session limit, and callback dispatching.
    """

    def __init__(
        self,
        bot_id: str,
        system_instruction: str,
        on_audio_chunk: AudioChunkCallback,
        on_turn_complete: TurnCompleteCallback,
        on_text_chunk: TextChunkCallback,
    ) -> None:
        self.bot_id = bot_id
        self._system_instruction = system_instruction
        self._on_audio_chunk = on_audio_chunk
        self._on_turn_complete = on_turn_complete
        self._on_text_chunk = on_text_chunk

        self._client: genai.Client | None = None
        self._session: Any = None
        self._session_ctx: Any = None  # async context manager from live.connect()
        self._receive_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._connected = False
        self._session_start: float = 0.0
        self._resumption_handle: str | None = None

        # Accumulation buffers for current turn
        self._audio_buffer = bytearray()
        self._text_buffer: list[str] = []

        # Diagnostic counters
        self._audio_chunks_sent = 0
        self._audio_bytes_sent = 0
        self._audio_chunks_received = 0
        self._send_error_logged = False

    async def connect(self) -> None:
        """Establish connection to Gemini Live API."""
        self._client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gcp_location,
        )

        config = self._build_config()

        self._session_ctx = self._client.aio.live.connect(
            model=settings.gemini_live_model,
            config=config,
        )
        self._session = await self._session_ctx.__aenter__()
        self._connected = True
        self._session_start = time.monotonic()
        logger.info("Gemini Live session connected for bot %s", self.bot_id)

        self._receive_task = asyncio.create_task(self._receive_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_timer())

    def _build_config(self) -> types.LiveConnectConfig:
        """Build the LiveConnectConfig with current settings."""
        resumption_config = types.SessionResumptionConfig(
            handle=self._resumption_handle,
        )

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(parts=[types.Part(text=self._system_instruction)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=settings.gemini_live_voice_name,
                    ),
                ),
                language_code=settings.gemini_live_language_code,
            ),
            generation_config=types.GenerationConfig(
                temperature=settings.gemini_live_temperature,
            ),
            session_resumption=resumption_config,
            enable_affective_dialog=settings.gemini_live_enable_affective_dialog,
        )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send PCM audio data to Gemini Live API.

        Args:
            pcm_bytes: Raw PCM 16kHz 16-bit mono audio data from Recall.ai.
        """
        if not self._connected or self._session is None:
            return

        self._audio_chunks_sent += 1
        self._audio_bytes_sent += len(pcm_bytes)

        try:
            await self._session.send_realtime_input(audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000"))
            self._send_error_logged = False
            if self._audio_chunks_sent == 1:
                logger.info("First audio chunk sent to Gemini (bot=%s, %d bytes)", self.bot_id, len(pcm_bytes))
            elif self._audio_chunks_sent % 100 == 0:
                logger.info(
                    "Audio stats (bot=%s): %d chunks sent, %d bytes total",
                    self.bot_id,
                    self._audio_chunks_sent,
                    self._audio_bytes_sent,
                )
        except Exception:
            if not self._send_error_logged:
                logger.warning("Gemini send failed (bot=%s), triggering reconnect", self.bot_id)
                self._send_error_logged = True
                self._connected = False
                asyncio.create_task(self._reconnect())

    async def _receive_loop(self) -> None:
        """Receive responses from Gemini Live API and dispatch callbacks."""
        if self._session is None:
            return

        logger.info("Receive loop started for bot %s", self.bot_id)
        try:
            async for response in self._session.receive():
                server_content = getattr(response, "server_content", None)
                if server_content is None:
                    # Check for session resumption update
                    resumption_update = getattr(response, "session_resumption_update", None)
                    if resumption_update:
                        handle = getattr(resumption_update, "handle", None)
                        if handle:
                            self._resumption_handle = handle
                            logger.info("Session resumption handle received (bot=%s)", self.bot_id)
                    continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn and model_turn.parts:
                    for part in model_turn.parts:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data and inline_data.data:
                            self._audio_chunks_received += 1
                            self._audio_buffer.extend(inline_data.data)
                            if self._audio_chunks_received == 1:
                                logger.info(
                                    "First audio chunk from Gemini (bot=%s, %d bytes)",
                                    self.bot_id,
                                    len(inline_data.data),
                                )
                            try:
                                self._on_audio_chunk(inline_data.data)
                            except Exception:
                                logger.exception("on_audio_chunk callback error (bot=%s)", self.bot_id)

                # Capture output audio transcription text
                output_transcription = getattr(server_content, "output_transcription", None)
                if output_transcription:
                    transcript_text = getattr(output_transcription, "text", None)
                    if transcript_text:
                        self._text_buffer.append(transcript_text)
                        logger.debug("Gemini transcription chunk (bot=%s): %s", self.bot_id, transcript_text[:80])
                        try:
                            self._on_text_chunk(transcript_text)
                        except Exception:
                            logger.exception("on_text_chunk callback error (bot=%s)", self.bot_id)

                turn_complete = getattr(server_content, "turn_complete", False)
                if turn_complete:
                    audio_data = bytes(self._audio_buffer)
                    text_data = "".join(self._text_buffer)
                    self._audio_buffer.clear()
                    self._text_buffer.clear()

                    logger.info(
                        "Turn complete (bot=%s): %d bytes audio, text=%s",
                        self.bot_id,
                        len(audio_data),
                        text_data[:120] if text_data else "(none)",
                    )

                    if audio_data or text_data:
                        try:
                            result = self._on_turn_complete(audio_data, text_data)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.exception("on_turn_complete callback error (bot=%s)", self.bot_id)

        except asyncio.CancelledError:
            logger.info("Receive loop cancelled for bot %s", self.bot_id)
        except Exception:
            logger.exception("Receive loop error for bot %s", self.bot_id)
            # Auto-reconnect on unexpected disconnection
            if self._connected:
                logger.info("Triggering auto-reconnect after receive loop error (bot=%s)", self.bot_id)
                asyncio.create_task(self._reconnect())

    async def _reconnect_timer(self) -> None:
        """Auto-reconnect before the 15-minute session limit."""
        try:
            await asyncio.sleep(settings.gemini_live_session_timeout_seconds)
            if self._connected:
                logger.info(
                    "Session timeout approaching, reconnecting (bot=%s, elapsed=%ds)",
                    self.bot_id,
                    int(time.monotonic() - self._session_start),
                )
                await self._reconnect()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Reconnect timer error (bot=%s)", self.bot_id)

    async def _reconnect(self) -> None:
        """Reconnect to Gemini Live API using session resumption."""
        self._connected = False

        # Close existing session via context manager
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing old session (bot=%s)", self.bot_id, exc_info=True)
            self._session = None
            self._session_ctx = None

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task

        # Reconnect with resumption handle
        try:
            config = self._build_config()
            self._session_ctx = self._client.aio.live.connect(
                model=settings.gemini_live_model,
                config=config,
            )
            self._session = await self._session_ctx.__aenter__()
            self._connected = True
            self._send_error_logged = False
            self._session_start = time.monotonic()
            logger.info(
                "Gemini Live session reconnected for bot %s (resumption=%s)",
                self.bot_id,
                bool(self._resumption_handle),
            )
        except Exception:
            logger.exception("Failed to reconnect Gemini session (bot=%s)", self.bot_id)
            return

        self._receive_task = asyncio.create_task(self._receive_loop())

        # Reset reconnect timer
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = asyncio.create_task(self._reconnect_timer())

    async def disconnect(self) -> None:
        """Close the session and cancel background tasks."""
        self._connected = False

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task

        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing session (bot=%s)", self.bot_id, exc_info=True)

        self._session = None
        self._session_ctx = None
        logger.info("Gemini Live session disconnected for bot %s", self.bot_id)

    @property
    def connected(self) -> bool:
        return self._connected


class GeminiLiveManager:
    """Manages bot_id → GeminiLiveSession mappings."""

    def __init__(self) -> None:
        self._sessions: dict[str, GeminiLiveSession] = {}

    async def create_session(
        self,
        bot_id: str,
        system_instruction: str,
        on_audio_chunk: AudioChunkCallback,
        on_turn_complete: TurnCompleteCallback,
        on_text_chunk: TextChunkCallback,
    ) -> GeminiLiveSession:
        """Create and connect a new Gemini Live session for a bot."""
        if bot_id in self._sessions:
            await self.remove_session(bot_id)

        session = GeminiLiveSession(
            bot_id=bot_id,
            system_instruction=system_instruction,
            on_audio_chunk=on_audio_chunk,
            on_turn_complete=on_turn_complete,
            on_text_chunk=on_text_chunk,
        )
        await session.connect()
        self._sessions[bot_id] = session
        logger.info("Live session created for bot %s (total=%d)", bot_id, len(self._sessions))
        return session

    async def remove_session(self, bot_id: str) -> None:
        """Disconnect and remove a session."""
        session = self._sessions.pop(bot_id, None)
        if session:
            await session.disconnect()
            logger.info("Live session removed for bot %s (total=%d)", bot_id, len(self._sessions))

    def get_session(self, bot_id: str) -> GeminiLiveSession | None:
        """Get an active session by bot_id."""
        return self._sessions.get(bot_id)

    def has_session(self, bot_id: str) -> bool:
        """Check if a live session exists for the given bot_id."""
        return bot_id in self._sessions

    async def shutdown(self) -> None:
        """Disconnect all sessions."""
        bot_ids = list(self._sessions.keys())
        for bot_id in bot_ids:
            await self.remove_session(bot_id)
        logger.info("All Gemini Live sessions shut down")
