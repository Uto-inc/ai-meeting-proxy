from __future__ import annotations

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

# Mapping of bot_id -> meeting_id for DB persistence
_bot_meeting_map: dict[str, str] = {}


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
    meeting_id: str | None = body.get("meeting_id")

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
        if meeting_id:
            # Use meeting-aware conversation session
            from bot.meeting_conversation import MeetingConversationSession

            repo = getattr(request.app.state, "repo", None)
            if repo:
                materials = await repo.list_materials(meeting_id)
                if materials:
                    session = MeetingConversationSession(bot_id, meeting_id, bot_name)
                    session.build_materials_context_from_list(materials)
                    _conversation_manager._sessions[bot_id] = session
                else:
                    _conversation_manager.get_or_create(bot_id, bot_name)
            else:
                _conversation_manager.get_or_create(bot_id, bot_name)

            _bot_meeting_map[bot_id] = meeting_id

            if repo:
                await repo.update_bot_status(meeting_id, bot_id, "joining")
        else:
            _conversation_manager.get_or_create(bot_id, bot_name)

    return JSONResponse(
        {
            "bot_id": bot_id,
            "status": result.get("status_changes"),
            "avatar_enabled": enable_avatar,
            "meeting_id": meeting_id,
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
    request: Request,
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

    # Update meeting status in DB
    meeting_id = _bot_meeting_map.pop(bot_id, None)
    if meeting_id:
        repo = getattr(request.app.state, "repo", None)
        if repo:
            await repo.update_bot_status(meeting_id, bot_id, "left")

    if _conversation_manager is not None:
        _conversation_manager.remove(bot_id)

    return JSONResponse({"bot_id": bot_id, "detail": "Leave request sent", "result": result})


async def _handle_avatar_response(bot_id: str, speaker: str, text: str, app_state: Any = None) -> None:
    """Process transcript through conversation pipeline and send audio response."""
    if _conversation_manager is None or _knowledge_base is None or _persona is None:
        logger.warning("Avatar components not initialized, skipping response")
        return

    session = _conversation_manager.get_or_create(bot_id)
    session.add_utterance(speaker, text)

    # Persist conversation to DB
    meeting_id = _bot_meeting_map.get(bot_id)
    repo = getattr(app_state, "repo", None) if app_state else None
    if repo and meeting_id:
        try:
            await repo.add_conversation_entry(meeting_id, bot_id, speaker, text, "human")
        except Exception:
            logger.exception("Failed to persist conversation entry")

    if not session.should_respond(speaker, text):
        return

    session.is_responding = True
    try:
        knowledge_context = _knowledge_base.get_context(text)

        # Use meeting-aware prompt if available
        from bot.meeting_conversation import MeetingConversationSession

        if isinstance(session, MeetingConversationSession):
            system_prompt = session.build_meeting_system_prompt(
                _persona.build_meeting_system_prompt(knowledge_context, session.materials_context)
            )
        else:
            system_prompt = _persona.build_system_prompt(knowledge_context)

        conversation_prompt = session.build_conversation_prompt(speaker, text)
        full_prompt = f"{system_prompt}\n\n{conversation_prompt}"

        from fastapi.concurrency import run_in_threadpool
        from vertexai.generative_models import GenerationConfig, GenerativeModel

        from config import settings as cfg

        model = GenerativeModel(cfg.gemini_model)
        gen_config = GenerationConfig(max_output_tokens=150, temperature=0.7)
        response = await run_in_threadpool(model.generate_content, full_prompt, generation_config=gen_config)
        response_text = (response.text or "").strip()

        if not response_text:
            logger.warning("Gemini returned empty response for bot %s", bot_id)
            return

        # Classify response and clean tags
        clean_text, category = MeetingConversationSession.classify_response(response_text)

        session.add_bot_response(clean_text)
        logger.info("Bot %s response [%s]: %s", bot_id, category or "none", clean_text[:120])

        # Persist bot response to DB
        if repo and meeting_id:
            try:
                await repo.add_conversation_entry(meeting_id, bot_id, session.bot_name, clean_text, "bot", category)
            except Exception:
                logger.exception("Failed to persist bot response")

        from bot.tts import is_available as tts_available
        from bot.tts import synthesize_to_base64

        if not tts_available():
            logger.warning("TTS not available, skipping audio output")
            return

        b64_audio = await run_in_threadpool(synthesize_to_base64, clean_text)

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
        # Restore bot-meeting mapping from DB if lost (e.g. after server restart)
        if bot_id not in _bot_meeting_map:
            repo = getattr(request.app.state, "repo", None)
            if repo:
                try:
                    meetings = await repo.list_meetings(ai_enabled_only=True)
                    for m in meetings:
                        if m.get("bot_id") == bot_id:
                            _bot_meeting_map[bot_id] = m["id"]
                            # Recreate meeting-aware session with materials
                            from bot.meeting_conversation import MeetingConversationSession

                            materials = await repo.list_materials(m["id"])
                            if materials:
                                session = MeetingConversationSession(bot_id, m["id"], settings.bot_display_name)
                                session.build_materials_context_from_list(materials)
                                _conversation_manager._sessions[bot_id] = session
                                logger.info(
                                    "Restored meeting session for bot %s (meeting=%s, %d materials)",
                                    bot_id,
                                    m["id"],
                                    len(materials),
                                )
                            break
                except Exception:
                    logger.exception("Failed to restore bot-meeting mapping")

        asyncio.create_task(_handle_avatar_response(bot_id, speaker, text.strip(), request.app.state))

    return JSONResponse(
        {
            "status": "received",
            "speaker": speaker,
            "transcript_length": len(text),
        }
    )
