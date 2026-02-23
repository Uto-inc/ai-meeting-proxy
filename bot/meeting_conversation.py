"""Extended conversation session with material awareness and response classification."""

from __future__ import annotations

import logging
import re
from typing import Any

from bot.conversation import ConversationSession

logger = logging.getLogger("meeting-proxy.bot.meeting")

_CATEGORY_PATTERN = re.compile(r"\[(ANSWERED|TAKEN_BACK)\]\s*", re.IGNORECASE)


class MeetingConversationSession(ConversationSession):
    """Conversation session that integrates meeting materials and classifies responses."""

    def __init__(
        self,
        bot_id: str,
        meeting_id: str,
        bot_name: str | None = None,
        materials_context: str = "",
    ) -> None:
        super().__init__(bot_id, bot_name)
        self.meeting_id = meeting_id
        self._materials_context = materials_context

    @property
    def materials_context(self) -> str:
        return self._materials_context

    @materials_context.setter
    def materials_context(self, value: str) -> None:
        self._materials_context = value

    def build_meeting_system_prompt(self, base_persona_prompt: str) -> str:
        """Build an enhanced system prompt with material context and behavior rules."""
        parts = [base_persona_prompt]

        if self._materials_context:
            parts.extend(
                [
                    "",
                    "--- 添付資料 ---",
                    self._materials_context,
                ]
            )

        parts.extend(
            [
                "",
                "--- 行動ルール ---",
                "1. 資料について質問されたら、添付資料に基づいて説明",
                "2. 資料に答えがある → [ANSWERED] を回答の先頭に付けて直接回答",
                "3. 判断が必要な事項（予算承認、方針決定等）→ [TAKEN_BACK]「持ち帰って確認します」",
                "4. 資料にない情報 →「確認して後日回答します」",
                "5. 2〜3文の簡潔な回答（音声読み上げのため）",
                "6. [ANSWERED] または [TAKEN_BACK] タグは必ず回答の先頭に付けること",
            ]
        )

        return "\n".join(parts)

    @staticmethod
    def classify_response(text: str) -> tuple[str, str | None]:
        """Parse response to extract category tag and clean text.

        Returns (clean_text, category) where category is 'answered', 'taken_back', or None.
        """
        match = _CATEGORY_PATTERN.match(text)
        if match:
            tag = match.group(1).lower()
            category = tag.replace("_", "_")  # 'answered' or 'taken_back'
            clean_text = text[match.end() :].strip()
            return clean_text, category
        return text, None

    def build_materials_context_from_list(self, materials: list[dict[str, Any]]) -> str:
        """Build context string from a list of material records."""
        parts: list[str] = []
        for mat in materials:
            extracted = mat.get("extracted_text", "")
            if not extracted:
                continue
            # Truncate very long materials
            if len(extracted) > 5000:
                extracted = extracted[:5000] + "\n...(省略)"
            parts.append(f"[{mat['filename']}]\n{extracted}")

        self._materials_context = "\n\n".join(parts)
        return self._materials_context
