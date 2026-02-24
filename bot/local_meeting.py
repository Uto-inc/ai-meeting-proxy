"""Local meeting session integrating BrowserClient + AudioBridge + GeminiLive."""

from __future__ import annotations

import logging
import re
from typing import Any

from config import settings

logger = logging.getLogger("meeting-proxy.local-meeting")

_TAKEN_BACK_PATTERN = re.compile(r"持ち帰|確認して|検討し|後日|本人に確認")


def _classify_by_content(text: str) -> str | None:
    """Fallback classification based on response content."""
    if not text or len(text.strip()) < 5:
        return None
    if _TAKEN_BACK_PATTERN.search(text):
        return "taken_back"
    return "answered"


class LocalMeetingSession:
    """Manages a single local meeting: browser + audio + Gemini Live.

    Combines BrowserClient (Playwright), AudioBridge (sounddevice), and
    GeminiLiveSession to provide direct meeting participation without Recall.ai.
    """

    def __init__(
        self,
        bot_id: str,
        meeting_url: str,
        bot_name: str,
        browser: Any,
        live_manager: Any,
        repo: Any = None,
        meeting_id: str | None = None,
    ) -> None:
        self.bot_id = bot_id
        self.meeting_url = meeting_url
        self.bot_name = bot_name
        self._browser = browser
        self._live_manager = live_manager
        self._repo = repo
        self.meeting_id = meeting_id
        self._audio_bridge: Any = None
        self._gemini_session: Any = None

    async def start(self, system_instruction: str) -> None:
        """Start the local meeting session.

        1. Join meeting via browser
        2. Create Gemini Live session
        3. Start audio bridge (capture -> Gemini, Gemini -> playback)
        """
        from bot.audio_bridge import AudioBridge

        # Step 1: Join meeting via browser
        logger.info("Joining meeting via browser (bot=%s, url=%s)", self.bot_id, self.meeting_url)
        await self._browser.join_meeting(self.meeting_url, self.bot_name)

        # Step 2: Create Gemini Live session
        def _noop_audio(data: bytes) -> None:
            pass

        def _noop_text(data: str) -> None:
            pass

        self._gemini_session = await self._live_manager.create_session(
            bot_id=self.bot_id,
            system_instruction=system_instruction,
            on_audio_chunk=_noop_audio,
            on_turn_complete=self._handle_turn,
            on_text_chunk=_noop_text,
        )
        logger.info("Gemini Live session created (bot=%s)", self.bot_id)

        # Step 3: Start audio bridge
        self._audio_bridge = AudioBridge()

        async def _send_audio_to_gemini(pcm_bytes: bytes) -> None:
            if self._gemini_session is not None:
                await self._gemini_session.send_audio(pcm_bytes)

        await self._audio_bridge.start(on_audio_chunk=_send_audio_to_gemini)
        logger.info("Audio bridge started (bot=%s)", self.bot_id)

    async def _handle_turn(self, audio_data: bytes, text_data: str) -> None:
        """Handle Gemini turn completion: play audio and persist response."""
        if audio_data and self._audio_bridge is not None:
            # Echo suppression: mute input while playing response
            playback_seconds = len(audio_data) / (settings.gemini_live_output_sample_rate * 2)
            mute_seconds = min(max(playback_seconds + 0.6, 0.5), 12.0)

            if self._gemini_session is not None:
                self._gemini_session.set_mute_duration(0.5)  # Pre-mute

            # Play audio through BlackHole 16ch -> Meet microphone
            self._audio_bridge.play_audio(audio_data, settings.gemini_live_output_sample_rate)

            if self._gemini_session is not None:
                self._gemini_session.set_mute_duration(mute_seconds)

            logger.info(
                "Local audio response played (bot=%s, %d bytes, %.1fs, mute=%.1fs)",
                self.bot_id,
                len(audio_data),
                playback_seconds,
                mute_seconds,
            )

        # Persist bot response to DB
        if text_data:
            await self._persist_response(text_data)

    async def _persist_response(self, text: str) -> None:
        """Classify and persist bot response to the database."""
        from bot.meeting_conversation import MeetingConversationSession

        clean_text, category = MeetingConversationSession.classify_response(text)
        if category is None:
            category = _classify_by_content(clean_text)

        if self._repo and self.meeting_id:
            try:
                await self._repo.add_conversation_entry(
                    self.meeting_id,
                    self.bot_id,
                    self.bot_name,
                    clean_text,
                    "bot",
                    category,
                )
                logger.info("Local bot response persisted [%s]: %s", category or "none", clean_text[:120])
            except Exception:
                logger.exception("Failed to persist local bot response (bot=%s)", self.bot_id)

    async def stop(self) -> None:
        """Stop the local meeting session: audio -> browser -> Gemini."""
        # Stop audio bridge first
        if self._audio_bridge is not None:
            try:
                await self._audio_bridge.stop()
            except Exception:
                logger.exception("Error stopping audio bridge (bot=%s)", self.bot_id)
            self._audio_bridge = None

        # Leave meeting via browser
        try:
            await self._browser.leave_meeting(self.bot_id)
        except Exception:
            logger.exception("Error leaving meeting via browser (bot=%s)", self.bot_id)

        # Remove Gemini Live session
        if self._live_manager is not None and self._live_manager.has_session(self.bot_id):
            try:
                await self._live_manager.remove_session(self.bot_id)
            except Exception:
                logger.exception("Error removing Gemini session (bot=%s)", self.bot_id)
        self._gemini_session = None

        # Update DB status
        if self._repo and self.meeting_id:
            try:
                await self._repo.update_bot_status(self.meeting_id, self.bot_id, "left")
            except Exception:
                logger.exception("Error updating bot status (bot=%s)", self.bot_id)

        logger.info("Local meeting session stopped (bot=%s)", self.bot_id)
