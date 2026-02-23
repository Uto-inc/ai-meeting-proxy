"""Gemini-based meeting minutes generation."""

import json
import logging
from typing import Any

from vertexai.generative_models import GenerativeModel

from config import settings

logger = logging.getLogger("meeting-proxy.minutes")

_MINUTES_PROMPT = """以下の会議の会話ログから、構造化された議事録を日本語で生成してください。

--- 会議情報 ---
タイトル: {title}
開始: {start_time}
終了: {end_time}
{description_section}

--- 会話ログ ---
{conversation_log}

--- 出力形式 ---
以下のJSONフォーマットで出力してください。必ず有効なJSONのみを出力してください。

{{
  "summary": "会議の概要（3〜5文）",
  "answered_items": [
    {{"question": "質問内容", "answer": "回答内容", "speaker": "質問者"}}
  ],
  "taken_back_items": [
    {{"topic": "持ち帰り事項", "reason": "持ち帰り理由", "raised_by": "提起者"}}
  ],
  "action_items": [
    {{"task": "タスク内容", "owner": "担当者", "deadline": "期限（あれば）"}}
  ],
  "full_markdown": "# 議事録\\n\\n完全なMarkdown形式の議事録"
}}
"""


def build_minutes_prompt(
    meeting: dict[str, Any],
    conversation_entries: list[dict[str, Any]],
) -> str:
    """Build the Gemini prompt for minutes generation."""
    desc_section = ""
    if meeting.get("description"):
        desc_section = f"説明: {meeting['description']}"

    log_lines: list[str] = []
    for entry in conversation_entries:
        category = ""
        if entry.get("response_category"):
            category = f" [{entry['response_category'].upper()}]"
        log_lines.append(f"[{entry.get('timestamp', '')}] {entry['speaker']}: {entry['text']}{category}")

    return _MINUTES_PROMPT.format(
        title=meeting.get("title", ""),
        start_time=meeting.get("start_time", ""),
        end_time=meeting.get("end_time", ""),
        description_section=desc_section,
        conversation_log="\n".join(log_lines),
    )


def generate_minutes(prompt: str) -> dict[str, Any]:
    """Call Gemini to generate structured meeting minutes."""
    model = GenerativeModel(settings.gemini_model)
    response = model.generate_content(prompt)
    text = (response.text or "").strip()

    if not text:
        logger.warning("Gemini returned empty minutes response")
        return _empty_minutes()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
        logger.info("Minutes generated successfully")
        return parsed
    except json.JSONDecodeError:
        logger.warning("Failed to parse Gemini minutes as JSON, using raw text")
        return {
            "summary": text[:500],
            "answered_items": [],
            "taken_back_items": [],
            "action_items": [],
            "full_markdown": text,
        }


def _empty_minutes() -> dict[str, Any]:
    return {
        "summary": "",
        "answered_items": [],
        "taken_back_items": [],
        "action_items": [],
        "full_markdown": "",
    }
