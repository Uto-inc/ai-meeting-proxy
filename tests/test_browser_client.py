"""Tests for bot.browser_client.BrowserClient."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings


def _set_default_test_settings() -> None:
    settings.meeting_mode = "local"
    settings.chrome_profile_dir = ""
    settings.api_key = None


def _mock_locator(count: int = 0) -> MagicMock:
    """Create a mock Playwright locator with configurable count."""
    locator = MagicMock()
    locator.count = AsyncMock(return_value=count)
    locator.first = MagicMock()
    locator.first.click = AsyncMock()
    locator.first.fill = AsyncMock()
    return locator


def _make_mock_page() -> MagicMock:
    """Create a mock Playwright page with locator always returning count=0."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.close = AsyncMock()
    page.locator = MagicMock(return_value=_mock_locator(count=0))
    return page


@pytest.mark.asyncio
async def test_browser_client_generates_bot_id() -> None:
    """join_meeting returns a valid UUID bot_id."""
    _set_default_test_settings()

    mock_page = _make_mock_page()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    from bot.browser_client import BrowserClient

    client = BrowserClient()
    client._context = mock_context

    bot_id = await client.join_meeting("https://meet.google.com/abc-defg-hij", "Test Bot")

    # Verify bot_id is a valid UUID
    parsed = uuid.UUID(bot_id)
    assert str(parsed) == bot_id
    assert bot_id in client._pages


@pytest.mark.asyncio
async def test_browser_client_leave() -> None:
    """leave_meeting removes the page and cleans up state."""
    _set_default_test_settings()

    mock_page = _make_mock_page()

    from bot.browser_client import BrowserClient

    client = BrowserClient()
    bot_id = "test-bot-123"
    client._pages[bot_id] = mock_page

    await client.leave_meeting(bot_id)

    assert bot_id not in client._pages
    mock_page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_client_leave_nonexistent() -> None:
    """leave_meeting with unknown bot_id does not raise."""
    _set_default_test_settings()

    from bot.browser_client import BrowserClient

    client = BrowserClient()
    await client.leave_meeting("nonexistent-bot")  # Should not raise


@pytest.mark.asyncio
async def test_browser_client_active_bots() -> None:
    """active_bots property returns current page keys."""
    from bot.browser_client import BrowserClient

    client = BrowserClient()
    assert client.active_bots == []

    client._pages["bot-1"] = MagicMock()
    client._pages["bot-2"] = MagicMock()
    assert sorted(client.active_bots) == ["bot-1", "bot-2"]
