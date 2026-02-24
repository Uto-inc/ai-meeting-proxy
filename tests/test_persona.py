import tempfile

from bot.persona import Persona


def _write_profile(content: str) -> str:
    """Write a profile to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmpfile:
        tmpfile.write(content)
        return tmpfile.name


def test_loads_profile_with_name() -> None:
    path = _write_profile("# Profile\n- Name: Taro\n- Role: Engineer\n")
    persona = Persona(path)
    assert persona.name == "Taro"


def test_default_profile_when_file_missing() -> None:
    persona = Persona("/nonexistent/profile.md")
    assert persona.name == "AI Avatar"
    assert persona.raw_profile != ""


def test_build_system_prompt_includes_persona() -> None:
    path = _write_profile("# Profile\n- Name: Hanako\n- Role: Designer\n")
    persona = Persona(path)
    prompt = persona.build_system_prompt()
    assert "Hanako" in prompt
    assert "ペルソナ" in prompt


def test_build_system_prompt_includes_knowledge_context() -> None:
    path = _write_profile("# Profile\n- Name: Test\n")
    persona = Persona(path)
    prompt = persona.build_system_prompt(knowledge_context="FastAPI is a web framework.")
    assert "FastAPI" in prompt
    assert "参考資料" in prompt


# --- build_live_system_prompt ---


def test_build_live_system_prompt_basic() -> None:
    path = _write_profile("# Profile\n- Name: Taro\n- Role: Engineer\n")
    persona = Persona(path)
    prompt = persona.build_live_system_prompt()
    assert "Taro" in prompt
    assert "ペルソナ情報" in prompt
    assert "禁止事項" in prompt
    assert "何でしょうか" in prompt


def test_build_live_system_prompt_no_tags() -> None:
    path = _write_profile("# Profile\n- Name: Taro\n")
    persona = Persona(path)
    prompt = persona.build_live_system_prompt(knowledge_context="some context", materials_context="doc content")
    assert "[ANSWERED]" not in prompt
    assert "[TAKEN_BACK]" not in prompt
    assert "---" not in prompt


def test_build_live_system_prompt_with_materials() -> None:
    path = _write_profile("# Profile\n- Name: Hanako\n- Role: PM\n")
    persona = Persona(path)
    prompt = persona.build_live_system_prompt(
        knowledge_context="KB info here",
        materials_context="Q3の売上は1000万円です。",
    )
    assert "KB info here" in prompt
    assert "Q3の売上は1000万円です" in prompt
    assert "添付資料" in prompt
    assert "ナレッジベース" in prompt
