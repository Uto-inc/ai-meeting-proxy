"""Admin API endpoints for managing avatar bot configuration."""

from __future__ import annotations

import hmac
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from config import settings

logger = logging.getLogger("meeting-proxy.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.(md|txt)$")


def _admin_auth_guard(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """HMAC API key guard for admin endpoints (same pattern as main app)."""
    if not settings.api_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _validate_filename(filename: str) -> Path:
    """Validate filename and return resolved path inside knowledge dir."""
    if not _FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename. Use alphanumeric, dash, underscore with .md or .txt extension",
        )
    knowledge_dir = Path(settings.knowledge_dir).resolve()
    target = (knowledge_dir / filename).resolve()
    if not str(target).startswith(str(knowledge_dir)):
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return target


def _get_singletons() -> tuple[Any, Any, Any]:
    """Get persona, knowledge_base, conversation_manager from bot.router."""
    from bot.router import get_conversation_manager, get_knowledge_base, get_persona

    return get_persona(), get_knowledge_base(), get_conversation_manager()


# --- Status ---


@router.get("/status")
def admin_status(_: None = Depends(_admin_auth_guard)) -> JSONResponse:
    """System status overview."""
    from bot.tts import is_available as tts_available

    persona, kb, cm = _get_singletons()
    return JSONResponse(
        {
            "tts_available": tts_available(),
            "persona_loaded": persona is not None,
            "persona_name": persona.name if persona else None,
            "knowledge_docs": kb.document_count if kb else 0,
            "active_sessions": cm.active_sessions if cm else 0,
        }
    )


# --- Profile ---


@router.get("/profile")
def get_profile(_: None = Depends(_admin_auth_guard)) -> JSONResponse:
    """Get persona profile content."""
    profile_path = Path(settings.persona_profile_path)
    if not profile_path.exists():
        return JSONResponse({"content": "", "path": str(profile_path)})
    content = profile_path.read_text(encoding="utf-8")
    return JSONResponse({"content": content, "path": str(profile_path)})


@router.put("/profile")
async def update_profile(
    request: Request,
    _: None = Depends(_admin_auth_guard),
) -> JSONResponse:
    """Update persona profile and reload."""
    body = await request.json()
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="content is required")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be a string")

    profile_path = Path(settings.persona_profile_path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(content, encoding="utf-8")

    persona, _, _ = _get_singletons()
    if persona:
        persona.reload()

    return JSONResponse({"status": "saved", "path": str(profile_path)})


# --- Settings ---


@router.get("/settings")
def get_settings(_: None = Depends(_admin_auth_guard)) -> JSONResponse:
    """Get current TTS/bot settings."""
    return JSONResponse(
        {
            "tts_voice_name": settings.tts_voice_name,
            "tts_speaking_rate": settings.tts_speaking_rate,
            "bot_display_name": settings.bot_display_name,
            "response_triggers": settings.response_triggers,
            "silence_timeout_seconds": settings.silence_timeout_seconds,
            "max_conversation_history": settings.max_conversation_history,
        }
    )


@router.put("/settings")
async def update_settings(
    request: Request,
    _: None = Depends(_admin_auth_guard),
) -> JSONResponse:
    """Update TTS/bot settings (runtime only, not persisted to .env)."""
    body = await request.json()
    updated: list[str] = []

    allowed = {
        "tts_voice_name": str,
        "tts_speaking_rate": (int, float),
        "bot_display_name": str,
        "response_triggers": str,
        "silence_timeout_seconds": int,
        "max_conversation_history": int,
    }

    for key, expected_type in allowed.items():
        if key in body:
            value = body[key]
            if not isinstance(value, expected_type):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid type for {key}",
                )
            setattr(settings, key, value)
            updated.append(key)

    return JSONResponse({"status": "updated", "fields": updated})


# --- TTS Preview ---


@router.post("/tts/preview")
async def tts_preview(
    request: Request,
    _: None = Depends(_admin_auth_guard),
) -> Response:
    """Synthesize text to MP3 audio for preview."""
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="text too long (max 500 chars)")

    from bot.tts import is_available as tts_available
    from bot.tts import synthesize_japanese

    if not tts_available():
        raise HTTPException(status_code=503, detail="TTS is not available")

    audio_bytes = synthesize_japanese(text)
    return Response(content=audio_bytes, media_type="audio/mpeg")


# --- Knowledge Base ---


@router.get("/knowledge")
def list_knowledge(_: None = Depends(_admin_auth_guard)) -> JSONResponse:
    """List knowledge base documents."""
    knowledge_dir = Path(settings.knowledge_dir)
    if not knowledge_dir.exists():
        return JSONResponse({"documents": []})

    documents: list[dict[str, Any]] = []
    for path in sorted(knowledge_dir.glob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            documents.append(
                {
                    "filename": path.name,
                    "size": path.stat().st_size,
                }
            )
    return JSONResponse({"documents": documents})


@router.get("/knowledge/{filename}")
def get_knowledge_doc(
    filename: str,
    _: None = Depends(_admin_auth_guard),
) -> JSONResponse:
    """Get a knowledge base document content."""
    target = _validate_filename(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    content = target.read_text(encoding="utf-8")
    return JSONResponse({"filename": filename, "content": content})


@router.put("/knowledge/{filename}")
async def put_knowledge_doc(
    filename: str,
    request: Request,
    _: None = Depends(_admin_auth_guard),
) -> JSONResponse:
    """Create or update a knowledge base document."""
    target = _validate_filename(filename)
    body = await request.json()
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="content is required")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be a string")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    _, kb, _ = _get_singletons()
    if kb:
        kb.reload()

    return JSONResponse({"status": "saved", "filename": filename})


@router.delete("/knowledge/{filename}")
def delete_knowledge_doc(
    filename: str,
    _: None = Depends(_admin_auth_guard),
) -> JSONResponse:
    """Delete a knowledge base document."""
    target = _validate_filename(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    target.unlink()

    _, kb, _ = _get_singletons()
    if kb:
        kb.reload()

    return JSONResponse({"status": "deleted", "filename": filename})
