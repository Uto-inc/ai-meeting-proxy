"""File-based knowledge retrieval for avatar bot responses."""

import logging
from pathlib import Path

from config import settings

logger = logging.getLogger("meeting-proxy.knowledge")


class KnowledgeBase:
    """Loads markdown/text files from a directory and provides keyword search."""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self._dir = Path(knowledge_dir or settings.knowledge_dir)
        self._documents: list[dict[str, str]] = []
        self._load_documents()

    def _load_documents(self) -> None:
        if not self._dir.exists():
            logger.warning("Knowledge directory does not exist: %s", self._dir)
            return

        for path in sorted(self._dir.glob("**/*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        self._documents.append(
                            {
                                "filename": path.name,
                                "path": str(path),
                                "content": content,
                            }
                        )
                        logger.info("Loaded knowledge: %s (%d chars)", path.name, len(content))
                except Exception:
                    logger.exception("Failed to load knowledge file: %s", path)

        logger.info("Knowledge base loaded: %d documents", len(self._documents))

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Search documents by keyword matching. Returns top matches."""
        if not query.strip() or not self._documents:
            return []

        keywords = [k.lower() for k in query.split() if len(k) >= 2]
        if not keywords:
            return []

        scored: list[tuple[int, dict[str, str]]] = []
        for doc in self._documents:
            content_lower = doc["content"].lower()
            score = sum(content_lower.count(kw) for kw in keywords)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:max_results]]

    def get_context(self, query: str, max_chars: int = 2000) -> str:
        """Build a context string from relevant documents for LLM prompt."""
        results = self.search(query)
        if not results:
            return ""

        parts: list[str] = []
        total = 0
        for doc in results:
            content = doc["content"]
            remaining = max_chars - total
            if remaining <= 0:
                break
            if len(content) > remaining:
                content = content[:remaining] + "..."
            parts.append(f"[{doc['filename']}]\n{content}")
            total += len(content)

        return "\n\n".join(parts)

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def reload(self) -> None:
        """Reload all documents from disk."""
        self._documents.clear()
        self._load_documents()
