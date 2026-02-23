"""Conversation session and manager for avatar bot meetings."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from config import settings

logger = logging.getLogger("meeting-proxy.conversation")


@dataclass
class Utterance:
    """A single utterance in the conversation."""

    speaker: str
    text: str
    timestamp: float = field(default_factory=time.time)


class ConversationSession:
    """Manages state for a single meeting session."""

    def __init__(self, bot_id: str, bot_name: str | None = None) -> None:
        self.bot_id = bot_id
        self.bot_name = bot_name or settings.bot_display_name
        self._history: list[Utterance] = []
        self._is_responding: bool = False
        self._triggers: list[str] = self._parse_triggers()

    def _parse_triggers(self) -> list[str]:
        """Parse response trigger words from settings."""
        triggers: list[str] = []
        if settings.response_triggers:
            triggers.extend(t.strip().lower() for t in settings.response_triggers.split(",") if t.strip())
        triggers.append(self.bot_name.lower())
        return triggers

    def add_utterance(self, speaker: str, text: str) -> None:
        """Record an utterance and trim history to max size."""
        self._history.append(Utterance(speaker=speaker, text=text))
        max_hist = settings.max_conversation_history
        if len(self._history) > max_hist:
            self._history = self._history[-max_hist:]

    def add_bot_response(self, text: str) -> None:
        """Record the bot's own response in history."""
        self.add_utterance(self.bot_name, text)

    def should_respond(self, speaker: str, text: str) -> bool:
        """Decide whether the bot should respond to this utterance."""
        if self._is_responding:
            return False

        text_lower = text.lower().strip()

        # Trigger 1: Bot name mentioned
        for trigger in self._triggers:
            if trigger in text_lower:
                logger.info("Response trigger: name/keyword '%s' in text", trigger)
                return True

        # Trigger 2: Direct question (Japanese question markers)
        if text_lower.endswith("？") or text_lower.endswith("?"):
            logger.info("Response trigger: question mark detected")
            return True
        if text_lower.endswith("か") or text_lower.endswith("か。"):
            logger.info("Response trigger: Japanese question ending detected")
            return True

        return False

    def build_conversation_prompt(self, current_speaker: str, current_text: str) -> str:
        """Build a conversation prompt including history for Gemini."""
        lines: list[str] = []

        if self._history:
            lines.append("--- 会話履歴 ---")
            for utterance in self._history[-10:]:
                lines.append(f"{utterance.speaker}: {utterance.text}")

        lines.append("")
        lines.append("--- 最新の発言 ---")
        lines.append(f"{current_speaker}: {current_text}")
        lines.append("")
        lines.append(f"上記の発言に対して、{self.bot_name}として簡潔に応答してください。")

        return "\n".join(lines)

    @property
    def is_responding(self) -> bool:
        return self._is_responding

    @is_responding.setter
    def is_responding(self, value: bool) -> None:
        self._is_responding = value

    @property
    def history(self) -> list[Utterance]:
        return list(self._history)

    @property
    def history_length(self) -> int:
        return len(self._history)


class ConversationManager:
    """Manages conversation sessions across multiple meetings."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get_or_create(self, bot_id: str, bot_name: str | None = None) -> ConversationSession:
        """Get existing session or create a new one."""
        if bot_id not in self._sessions:
            self._sessions[bot_id] = ConversationSession(bot_id, bot_name)
            logger.info("Created conversation session for bot %s", bot_id)
        return self._sessions[bot_id]

    def remove(self, bot_id: str) -> None:
        """Remove a session when the bot leaves."""
        if bot_id in self._sessions:
            del self._sessions[bot_id]
            logger.info("Removed conversation session for bot %s", bot_id)

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)
