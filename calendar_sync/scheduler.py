"""Background scheduler that auto-joins meetings 2 minutes before start."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings

logger = logging.getLogger("meeting-proxy.scheduler")

_scheduler_task: asyncio.Task | None = None


async def _check_and_join(repo: Any) -> None:
    """Check for upcoming AI-enabled meetings and join if within 2 minutes."""
    now = datetime.now(timezone.utc)
    window_start = now.isoformat()
    window_end = (now + timedelta(minutes=3)).isoformat()

    meetings = await repo.list_meetings(
        from_time=window_start,
        to_time=window_end,
        ai_enabled_only=True,
    )

    for meeting in meetings:
        if meeting["bot_status"] not in ("idle", "scheduled"):
            continue

        meeting_url = meeting.get("meeting_url")
        if not meeting_url:
            continue

        start_time = datetime.fromisoformat(meeting["start_time"].replace("Z", "+00:00"))
        time_until = (start_time - now).total_seconds()

        if time_until <= 120:
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

        from bot.router import get_conversation_manager

        cm = get_conversation_manager()
        if cm is not None:
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
