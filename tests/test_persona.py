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
