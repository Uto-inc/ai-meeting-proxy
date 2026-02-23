import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("meeting-proxy.recall")


class RecallClient:
    """Thin wrapper around the Recall.ai REST API."""

    def __init__(self) -> None:
        if not settings.recall_api_key:
            raise RuntimeError("RECALL_API_KEY is not configured")
        self._base_url = settings.recall_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Token {settings.recall_api_key}",
            "Content-Type": "application/json",
        }

    async def create_bot(self, meeting_url: str) -> dict[str, Any]:
        """Send a bot to join the given meeting URL."""
        payload: dict[str, Any] = {"meeting_url": meeting_url}
        if settings.webhook_base_url:
            webhook_base = settings.webhook_base_url.rstrip("/")
            payload["recording_config"] = {
                "transcript": {
                    "provider": {"recallai_streaming": {}},
                },
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": f"{webhook_base}/bot/webhook/transcript",
                        "events": ["transcript.data", "transcript.partial_data"],
                    },
                ],
            }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/bot",
                json=payload,
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.info("Bot created: id=%s", data.get("id"))
            return data

    async def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        """Get the current status of a bot."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base_url}/bot/{bot_id}",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data

    async def create_bot_with_audio(self, meeting_url: str, bot_name: str) -> dict[str, Any]:
        """Create a bot with Output Audio enabled for bidirectional voice."""
        payload: dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "output_media": {"audio": {"kind": "mp3"}},
        }
        if settings.webhook_base_url:
            webhook_base = settings.webhook_base_url.rstrip("/")
            payload["recording_config"] = {
                "transcript": {
                    "provider": {"recallai_streaming": {}},
                },
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": f"{webhook_base}/bot/webhook/transcript",
                        "events": ["transcript.data", "transcript.partial_data"],
                    },
                ],
            }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/bot",
                json=payload,
                headers=self._headers,
                timeout=30,
            )
            if resp.status_code >= 400:
                logger.error("Recall.ai error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.info("Bot created with audio: id=%s name=%s", data.get("id"), bot_name)
            return data

    async def send_audio(self, bot_id: str, b64_mp3: str) -> dict[str, Any]:
        """Send base64-encoded MP3 audio to the meeting via Output Audio API."""
        payload = {"kind": "mp3", "b64_data": b64_mp3}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/bot/{bot_id}/output_audio",
                json=payload,
                headers=self._headers,
                timeout=30,
            )
            if resp.status_code >= 400:
                logger.error("send_audio error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.info("Audio sent to bot %s", bot_id)
            return data

    async def leave_meeting(self, bot_id: str) -> dict[str, Any]:
        """Tell the bot to leave the meeting."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/bot/{bot_id}/leave_call",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.info("Bot %s leaving meeting", bot_id)
            return data
