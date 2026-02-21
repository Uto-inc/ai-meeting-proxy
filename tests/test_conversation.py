from bot.conversation import ConversationManager, ConversationSession
from config import settings


def _make_session(bot_name: str = "TestBot", triggers: str = "") -> ConversationSession:
    settings.bot_display_name = bot_name
    settings.response_triggers = triggers
    settings.max_conversation_history = 20
    return ConversationSession("bot-123", bot_name)


def test_add_utterance_records_history() -> None:
    session = _make_session()
    session.add_utterance("Alice", "Hello everyone")
    assert session.history_length == 1
    assert session.history[0].speaker == "Alice"


def test_history_trimmed_to_max() -> None:
    session = _make_session()
    settings.max_conversation_history = 3
    for i in range(5):
        session.add_utterance("Speaker", f"Message {i}")
    assert session.history_length == 3


def test_should_respond_when_name_called() -> None:
    session = _make_session(bot_name="Avatar")
    assert session.should_respond("Alice", "Avatar、この件どう思う？") is True


def test_should_not_respond_to_unrelated() -> None:
    session = _make_session(bot_name="Avatar")
    assert session.should_respond("Alice", "明日の天気はどうかな") is False


def test_should_respond_to_question_mark() -> None:
    session = _make_session(bot_name="Avatar")
    assert session.should_respond("Alice", "これどう思いますか？") is True


def test_should_respond_to_custom_trigger() -> None:
    session = _make_session(bot_name="Avatar", triggers="keyword1,keyword2")
    assert session.should_respond("Alice", "keyword1について教えて") is True


def test_should_not_respond_while_responding() -> None:
    session = _make_session(bot_name="Avatar")
    session.is_responding = True
    assert session.should_respond("Alice", "Avatar、聞こえる？") is False


def test_build_conversation_prompt_includes_history() -> None:
    session = _make_session(bot_name="Avatar")
    session.add_utterance("Alice", "先週のレビューの件ですが")
    prompt = session.build_conversation_prompt("Bob", "Avatar、どう思う？")
    assert "Alice" in prompt
    assert "Bob" in prompt
    assert "Avatar" in prompt


# --- ConversationManager ---


def test_manager_creates_and_retrieves_session() -> None:
    settings.bot_display_name = "TestBot"
    settings.response_triggers = ""
    settings.max_conversation_history = 20
    manager = ConversationManager()
    session = manager.get_or_create("bot-1", "TestBot")
    assert manager.active_sessions == 1
    same_session = manager.get_or_create("bot-1")
    assert session is same_session


def test_manager_removes_session() -> None:
    settings.bot_display_name = "TestBot"
    settings.response_triggers = ""
    settings.max_conversation_history = 20
    manager = ConversationManager()
    manager.get_or_create("bot-1", "TestBot")
    manager.remove("bot-1")
    assert manager.active_sessions == 0
