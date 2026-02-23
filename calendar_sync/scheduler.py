"""Background scheduler that auto-joins meetings 2 minutes before start."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from config import settings

logger = logging.getLogger("meeting-proxy.scheduler")

_scheduler_task: asyncio.Task | None = None


def _parse_meeting_time(time_str: str) -> datetime | None:
    """Parse meeting start_time to a timezone-aware datetime, or None for all-day events."""
    if not time_str or "T" not in time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


async def _check_and_join(repo: Any) -> None:
    """Check for upcoming AI-enabled meetings and join if within 2 minutes."""
    now = datetime.now(timezone.utc)

    meetings = await repo.list_meetings(ai_enabled_only=True)

    for meeting in meetings:
        if meeting["bot_status"] not in ("idle", "scheduled"):
            continue

        meeting_url = meeting.get("meeting_url")
        if not meeting_url:
            continue

        start_time = _parse_meeting_time(meeting["start_time"])
        if start_time is None:
            continue

        end_time = _parse_meeting_time(meeting.get("end_time", ""))
        time_until = (start_time - now).total_seconds()

        # Join if: within 2 min before start, OR meeting is currently in progress
        is_before_start = time_until <= 120
        is_not_ended = end_time is None or now < end_time
        if is_before_start and is_not_ended:
            logger.info(
                "Auto-joining meeting '%s' (starts in %.0fs)",
                meeting["title"],
                time_until,
            )
            await _join_meeting(repo, meeting)


async def _join_meeting(repo: Any, meeting: dict[str, Any]) -> None:
    """Send a Recall.ai bot to join the meeting."""
    try:
        from bot.recall_client import RecallClient

        if not settings.recall_api_key:
            logger.warning("Recall.ai not configured, cannot auto-join")
            return

        client = RecallClient()
        bot_name = settings.bot_display_name
        result = await client.create_bot_with_audio(meeting["meeting_url"], bot_name)
        bot_id = result.get("id", "")

        await repo.update_bot_status(meeting["id"], bot_id, "joining")
        logger.info("Bot %s joining meeting %s", bot_id, meeting["id"])

        from bot.router import _bot_meeting_map, get_conversation_manager

        _bot_meeting_map[bot_id] = meeting["id"]

        cm = get_conversation_manager()
        if cm is not None:
            # Load materials and create meeting-aware session
            materials = await repo.list_materials(meeting["id"])
            if materials:
                from bot.meeting_conversation import MeetingConversationSession

                session = MeetingConversationSession(bot_id, meeting["id"], bot_name)
                session.build_materials_context_from_list(materials)
                cm._sessions[bot_id] = session
                logger.info("Meeting session created with %d materials", len(materials))
            else:
                cm.get_or_create(bot_id, bot_name)

    except Exception:
        logger.exception("Failed to auto-join meeting %s", meeting["id"])
        await repo.update_bot_status(meeting["id"], None, "idle")


async def _scheduler_loop(repo: Any) -> None:
    """Run the scheduler check every 60 seconds."""
    logger.info("Meeting scheduler started (60s interval)")
    while True:
        try:
            await _check_and_join(repo)
        except Exception:
            logger.exception("Scheduler check failed")
        await asyncio.sleep(60)


def start_scheduler(repo: Any) -> None:
    """Start the background scheduler task."""
    global _scheduler_task
    if _scheduler_task is not None:
        logger.warning("Scheduler already running")
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop(repo))
    logger.info("Scheduler task created")


def stop_scheduler() -> None:
    """Cancel the background scheduler task."""
    global _scheduler_task
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        _scheduler_task = None
        logger.info("Scheduler stopped")
