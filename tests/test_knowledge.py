import tempfile
from pathlib import Path

from bot.knowledge import KnowledgeBase


def _create_temp_knowledge(docs: dict[str, str]) -> str:
    """Create a temp directory with knowledge docs and return its path."""
    tmpdir = tempfile.mkdtemp()
    for filename, content in docs.items():
        (Path(tmpdir) / filename).write_text(content, encoding="utf-8")
    return tmpdir


def test_loads_markdown_files() -> None:
    tmpdir = _create_temp_knowledge(
        {
            "doc1.md": "# Python\nPython is a programming language.",
            "doc2.txt": "FastAPI is a web framework.",
        }
    )
    kb = KnowledgeBase(tmpdir)
    assert kb.document_count == 2


def test_ignores_non_text_files() -> None:
    tmpdir = _create_temp_knowledge(
        {
            "doc.md": "Hello world",
            "image.png": "not-really-an-image",
        }
    )
    kb = KnowledgeBase(tmpdir)
    assert kb.document_count == 1


def test_search_returns_relevant_docs() -> None:
    tmpdir = _create_temp_knowledge(
        {
            "python.md": "Python is great for backend development.",
            "java.md": "Java is used in enterprise applications.",
        }
    )
    kb = KnowledgeBase(tmpdir)
    results = kb.search("Python backend")
    assert len(results) >= 1
    assert results[0]["filename"] == "python.md"


def test_search_empty_query_returns_empty() -> None:
    tmpdir = _create_temp_knowledge({"doc.md": "Some content"})
    kb = KnowledgeBase(tmpdir)
    assert kb.search("") == []


def test_get_context_builds_string() -> None:
    tmpdir = _create_temp_knowledge(
        {
            "info.md": "AI Meeting Proxy uses FastAPI and GCP.",
        }
    )
    kb = KnowledgeBase(tmpdir)
    context = kb.get_context("FastAPI GCP")
    assert "FastAPI" in context
    assert "[info.md]" in context


def test_empty_directory_returns_zero_docs() -> None:
    tmpdir = tempfile.mkdtemp()
    kb = KnowledgeBase(tmpdir)
    assert kb.document_count == 0
    assert kb.search("anything") == []
