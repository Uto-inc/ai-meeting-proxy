"""Tests for MeetingConversationSession."""

from bot.meeting_conversation import MeetingConversationSession


def test_classify_answered() -> None:
    text, cat = MeetingConversationSession.classify_response("[ANSWERED] その件は資料3ページに記載されています。")
    assert cat == "answered"
    assert text == "その件は資料3ページに記載されています。"


def test_classify_taken_back() -> None:
    text, cat = MeetingConversationSession.classify_response("[TAKEN_BACK] 持ち帰って確認します。")
    assert cat == "taken_back"
    assert text == "持ち帰って確認します。"


def test_classify_none() -> None:
    text, cat = MeetingConversationSession.classify_response("通常の応答です。")
    assert cat is None
    assert text == "通常の応答です。"


def test_build_materials_context() -> None:
    session = MeetingConversationSession("bot1", "meeting1")
    materials = [
        {"filename": "doc1.md", "extracted_text": "Content A"},
        {"filename": "doc2.pdf", "extracted_text": "Content B"},
        {"filename": "empty.txt", "extracted_text": ""},
    ]
    ctx = session.build_materials_context_from_list(materials)
    assert "[doc1.md]" in ctx
    assert "[doc2.pdf]" in ctx
    assert "empty.txt" not in ctx
    assert "Content A" in ctx
    assert "Content B" in ctx


def test_meeting_system_prompt_includes_materials() -> None:
    session = MeetingConversationSession("bot1", "meeting1")
    session.materials_context = "Budget: 1M JPY"
    prompt = session.build_meeting_system_prompt("Base prompt here")
    assert "添付資料" in prompt
    assert "Budget: 1M JPY" in prompt
    assert "行動ルール" in prompt


def test_meeting_session_inherits_conversation() -> None:
    session = MeetingConversationSession("bot1", "meeting1", bot_name="TestBot")
    session.add_utterance("Alice", "Hello")
    assert session.history_length == 1
    assert session.meeting_id == "meeting1"
