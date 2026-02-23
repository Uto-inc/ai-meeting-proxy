import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import HTTPStatusError

from config import settings

logger = logging.getLogger("meeting-proxy.bot")

router = APIRouter(tags=["bot"])

# Module-level singletons (initialized lazily or at startup)
_conversation_manager: Any = None
_knowledge_base: Any = None
_persona: Any = None


def _require_recall_configured() -> None:
    """Dependency that ensures Recall.ai is configured."""
    if not settings.recall_api_key:
        raise HTTPException(status_code=503, detail="Recall.ai is not configured")


def _get_recall_client() -> Any:
    """Build a RecallClient instance (lazy import to avoid startup errors)."""
    from bot.recall_client import RecallClient

    return RecallClient()


def get_persona() -> Any:
    """Return the module-level Persona singleton."""
    return _persona


def get_knowledge_base() -> Any:
    """Return the module-level KnowledgeBase singleton."""
    return _knowledge_base


def get_conversation_manager() -> Any:
    """Return the module-level ConversationManager singleton."""
    return _conversation_manager


def init_avatar_components() -> None:
    """Initialize conversation manager, knowledge base, and persona at startup."""
    global _conversation_manager, _knowledge_base, _persona

    from bot.conversation import ConversationManager
    from bot.knowledge import KnowledgeBase
    from bot.persona import Persona

    _conversation_manager = ConversationManager()
    _knowledge_base = KnowledgeBase()
    _persona = Persona()
    logger.info(
        "Avatar components initialized: knowledge=%d docs, persona=%s",
        _knowledge_base.document_count,
        _persona.name,
    )


@router.post("/join")
async def join_meeting(
    request: Request,
    _: None = Depends(_require_recall_configured),
) -> JSONResponse:
    """Send a Recall.ai bot to join a Google Meet meeting."""
    body = await request.json()
    meeting_url: str | None = body.get("meeting_url")
    if not meeting_url or not meeting_url.strip():
        raise HTTPException(status_code=400, detail="meeting_url is required")

    enable_avatar: bool = body.get("enable_avatar", False)
    bot_name: str = body.get("bot_name", settings.bot_display_name)

    client = _get_recall_client()
    try:
        if enable_avatar:
            result = await client.create_bot_with_audio(meeting_url.strip(), bot_name)
        else:
            result = await client.create_bot(meeting_url.strip())
    except HTTPStatusError as exc:
        logger.exception("Recall.ai create_bot failed")
        raise HTTPException(status_code=502, detail="Failed to create Recall.ai bot") from exc

    bot_id = result.get("id")

    if enable_avatar and _conversation_manager is not None:
        _conversation_manager.get_or_create(bot_id, bot_name)

    return JSONResponse(
        {
            "bot_id": bot_id,
            "status": result.get("status_changes"),
            "avatar_enabled": enable_avatar,
        }
    )


@router.get("/{bot_id}/status")
async def bot_status(
    bot_id: str,
    _: None = Depends(_require_recall_configured),
) -> JSONResponse:
    """Check the current status of a Recall.ai bot."""
    client = _get_recall_client()
    try:
        result = await client.get_bot_status(bot_id)
    except HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Bot not found") from exc
        logger.exception("Recall.ai get_bot_status failed")
        raise HTTPException(status_code=502, detail="Failed to get bot status") from exc
    return JSONResponse({"bot_id": bot_id, "status": result.get("status_changes")})


@router.post("/{bot_id}/leave")
async def leave_meeting(
    bot_id: str,
    _: None = Depends(_require_recall_configured),
) -> JSONResponse:
    """Tell a Recall.ai bot to leave the meeting."""
    client = _get_recall_client()
    try:
        result = await client.leave_meeting(bot_id)
    except HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Bot not found") from exc
        logger.exception("Recall.ai leave_meeting failed")
        raise HTTPException(status_code=502, detail="Failed to leave meeting") from exc

    if _conversation_manager is not None:
        _conversation_manager.remove(bot_id)

    return JSONResponse({"bot_id": bot_id, "detail": "Leave request sent", "result": result})


async def _handle_avatar_response(bot_id: str, speaker: str, text: str) -> None:
    """Process transcript through conversation pipeline and send audio response."""
    if _conversation_manager is None or _knowledge_base is None or _persona is None:
        logger.warning("Avatar components not initialized, skipping response")
        return

    session = _conversation_manager.get_or_create(bot_id)

    session.add_utterance(speaker, text)

    if not session.should_respond(speaker, text):
        return

    session.is_responding = True
    try:
        knowledge_context = _knowledge_base.get_context(text)
        system_prompt = _persona.build_system_prompt(knowledge_context)
        conversation_prompt = session.build_conversation_prompt(speaker, text)
        full_prompt = f"{system_prompt}\n\n{conversation_prompt}"

        from vertexai.generative_models import GenerativeModel

        from config import settings as cfg

        model = GenerativeModel(cfg.gemini_model)
        response = model.generate_content(full_prompt)
        response_text = (response.text or "").strip()

        if not response_text:
            logger.warning("Gemini returned empty response for bot %s", bot_id)
            return

        session.add_bot_response(response_text)
        logger.info("Bot %s response: %s", bot_id, response_text[:120])

        from bot.tts import is_available as tts_available
        from bot.tts import synthesize_to_base64

        if not tts_available():
            logger.warning("TTS not available, skipping audio output")
            return

        b64_audio = synthesize_to_base64(response_text)

        client = _get_recall_client()
        await client.send_audio(bot_id, b64_audio)
        logger.info("Audio response sent to bot %s", bot_id)

    except Exception:
        logger.exception("Avatar response pipeline failed for bot %s", bot_id)
    finally:
        session.is_responding = False


@router.post("/webhook/transcript")
async def webhook_transcript(request: Request) -> JSONResponse:
    """Receive real-time transcription events from Recall.ai."""
    body = await request.json()
    logger.info("Webhook received: event=%s", body.get("event"))

    data = body.get("data", {})
    inner = data.get("data", {})

    # Build text from words array
    words = inner.get("words", [])
    text = "".join(w.get("text", "") for w in words)

    # Speaker from participant
    participant = inner.get("participant", {})
    speaker = participant.get("name", "unknown")

    # Bot ID
    bot_id = data.get("bot", {}).get("id", "")

    if not text.strip():
        return JSONResponse({"status": "ignored", "reason": "empty transcript"})

    logger.info("Transcript from %s: %s", speaker, text[:120])

    if bot_id and _conversation_manager is not None:
        asyncio.create_task(_handle_avatar_response(bot_id, speaker, text.strip()))

    return JSONResponse(
        {
            "status": "received",
            "speaker": speaker,
            "transcript_length": len(text),
        }
    )
