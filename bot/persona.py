"""Persona profile loading and Gemini system prompt construction."""

from __future__ import annotations

import logging
from pathlib import Path

from config import settings

logger = logging.getLogger("meeting-proxy.persona")

_DEFAULT_PROFILE = {
    "name": "AI Avatar",
    "role": "Assistant",
    "style": "Professional and concise",
    "language": "Japanese",
}


class Persona:
    """Loads persona profile from markdown and builds system prompts."""

    def __init__(self, profile_path: str | None = None) -> None:
        self._path = Path(profile_path or settings.persona_profile_path)
        self._raw_profile: str = ""
        self._name: str = _DEFAULT_PROFILE["name"]
        self._load_profile()

    def _load_profile(self) -> None:
        if not self._path.exists():
            logger.warning("Persona profile not found: %s, using defaults", self._path)
            self._raw_profile = self._build_default_profile()
            return

        try:
            self._raw_profile = self._path.read_text(encoding="utf-8").strip()
            self._name = self._extract_name()
            logger.info("Persona loaded: %s (%d chars)", self._name, len(self._raw_profile))
        except Exception:
            logger.exception("Failed to load persona profile: %s", self._path)
            self._raw_profile = self._build_default_profile()

    def _extract_name(self) -> str:
        for line in self._raw_profile.splitlines():
            stripped = line.strip()
            if stripped.startswith("- Name:") or stripped.startswith("- name:"):
                return stripped.split(":", 1)[1].strip()
        return settings.bot_display_name

    def _build_default_profile(self) -> str:
        return (
            f"# Persona Profile\n\n"
            f"- Name: {_DEFAULT_PROFILE['name']}\n"
            f"- Role: {_DEFAULT_PROFILE['role']}\n"
            f"- Style: {_DEFAULT_PROFILE['style']}\n"
            f"- Language: {_DEFAULT_PROFILE['language']}\n"
        )

    def build_system_prompt(self, knowledge_context: str = "") -> str:
        """Build a system prompt for Gemini with persona and optional knowledge."""
        parts = [
            "あなたは以下のペルソナとして会議に参加しています。",
            "ペルソナになりきって、自然な日本語で応答してください。",
            "応答は音声で読み上げられるため、2〜3文程度の簡潔な回答を心がけてください。",
            "",
            "--- ペルソナ情報 ---",
            self._raw_profile,
        ]

        if knowledge_context:
            parts.extend(
                [
                    "",
                    "--- 参考資料 ---",
                    "以下の資料を参考にして回答してください:",
                    knowledge_context,
                ]
            )

        parts.extend(
            [
                "",
                "--- 応答ルール ---",
                "1. ペルソナの口調・専門性に合わせて応答する",
                "2. 知らないことは正直に「わかりません」と答える",
                "3. 音声出力のため、簡潔に2〜3文で回答する",
                "4. 自然な会話体で話す（書き言葉は避ける）",
            ]
        )

        return "\n".join(parts)

    @property
    def name(self) -> str:
        return self._name

    @property
    def raw_profile(self) -> str:
        return self._raw_profile

    def build_meeting_system_prompt(self, knowledge_context: str = "", materials_context: str = "") -> str:
        """Build a system prompt for meeting attendance with materials support."""
        parts = [
            f"あなたは{self._name}の代理として会議に出席しています。",
            "ペルソナになりきって、自然な日本語で応答してください。",
            "",
            "--- ペルソナ情報 ---",
            self._raw_profile,
        ]

        if knowledge_context:
            parts.extend(
                [
                    "",
                    "--- ナレッジベース ---",
                    knowledge_context,
                ]
            )

        if materials_context:
            parts.extend(
                [
                    "",
                    "--- 添付資料 ---",
                    materials_context,
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
            ]
        )

        return "\n".join(parts)

    def build_live_system_prompt(self, knowledge_context: str = "", materials_context: str = "") -> str:
        """Build a system prompt optimized for Gemini Live API voice output.

        Unlike build_meeting_system_prompt(), this prompt:
        - Does not use section dividers (--- ...) that could be read aloud
        - Does not include [ANSWERED]/[TAKEN_BACK] classification tags
        - Explicitly prohibits vague/generic responses
        - Encourages proactive, material-based answers
        """
        parts = [
            f"あなたは{self._name}の代理として会議に出席しています。",
            f"{self._name}になりきって、自然な日本語で音声応答してください。",
            "",
            "【ペルソナ情報】",
            self._raw_profile,
        ]

        if knowledge_context:
            parts.extend(
                [
                    "",
                    "【ナレッジベース】",
                    knowledge_context,
                ]
            )

        if materials_context:
            parts.extend(
                [
                    "",
                    "【添付資料】",
                    "以下の資料の内容を把握しています。質問されたら具体的な数値や内容を引用して回答してください。",
                    materials_context,
                ]
            )

        parts.extend(
            [
                "",
                "【応答ルール】",
                f"1. {self._name}の口調・専門性に合わせて応答する",
                "2. 資料について質問されたら、添付資料の具体的な内容を引用して回答する",
                "3. 判断が必要な事項（予算承認、方針決定等）は「持ち帰って本人に確認します」と答える",
                "4. 資料にない情報は「確認して後日回答します」と答える",
                "5. 知らないことは正直に「わかりません」と答える",
                "6. 2〜3文の簡潔な回答を心がける",
                "7. 自然な会話体で話す（書き言葉は避ける）",
                "",
                "【禁止事項】",
                "以下のような曖昧・汎用的な応答は絶対に避けてください:",
                "「はい、何でしょうか」「どのようなご用件でしょうか」「何かお手伝いできますか」",
                "「ご質問をどうぞ」「お聞きしています」",
                "会議の参加者として、具体的な議題や資料に基づいて積極的に会話に参加してください。",
            ]
        )

        return "\n".join(parts)

    def reload(self) -> None:
        """Reload persona profile from disk."""
        self._load_profile()
