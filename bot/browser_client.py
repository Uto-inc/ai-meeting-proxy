"""Playwright-based browser client for joining Google Meet meetings."""

from __future__ import annotations

import logging
import uuid

from config import settings

logger = logging.getLogger("meeting-proxy.browser-client")

# Selectors for Google Meet UI elements
_SEL_CAMERA_OFF = '[aria-label*="カメラ"][aria-label*="オフ"], [aria-label*="camera"][aria-label*="off"]'
_SEL_MIC_ON = '[aria-label*="マイク"][aria-label*="オン"], [aria-label*="microphone"][aria-label*="on"]'
_SEL_JOIN_BTN = 'button:has-text("今すぐ参加"), button:has-text("Join now"), button:has-text("参加")'
_SEL_ASK_JOIN = 'button:has-text("参加をリクエスト"), button:has-text("Ask to join")'
_SEL_IN_MEETING = "[data-meeting-title], [data-self-name]"
_SEL_NAME_INPUT = 'input[aria-label*="名前"], input[aria-label*="name"]'
_SEL_LEAVE_BTN = '[aria-label*="通話から退出"], [aria-label*="Leave call"]'
_SEL_END_FOR_ALL = 'button:has-text("通話から退出"), button:has-text("Leave call"), button:has-text("退出")'


class BrowserClient:
    """Manages a Playwright Chromium browser for Google Meet participation."""

    def __init__(self) -> None:
        self._playwright: object | None = None
        self._browser: object | None = None
        self._context: object | None = None
        self._pages: dict[str, object] = {}  # bot_id -> Page

    async def launch(self) -> None:
        """Launch a persistent Chromium browser context with audio routing."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        launch_args = [
            "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-features=WebRtcHideLocalIpsWithMdns",
            "--no-first-run",
            "--disable-default-apps",
        ]

        profile_dir = settings.chrome_profile_dir
        if profile_dir:
            self._context = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=launch_args,
                ignore_default_args=["--mute-audio"],
                permissions=["microphone", "camera"],
                locale="ja-JP",
            )
            self._browser = None
            logger.info("Persistent browser context launched (profile=%s)", profile_dir)
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=launch_args,
            )
            self._context = await self._browser.new_context(
                ignore_https_errors=True,
                permissions=["microphone", "camera"],
                locale="ja-JP",
            )
            logger.info("Ephemeral browser context launched")

    async def join_meeting(self, meeting_url: str, bot_name: str) -> str:
        """Join a Google Meet meeting and return a bot_id.

        Args:
            meeting_url: The Google Meet URL to join.
            bot_name: Display name for the bot participant.

        Returns:
            A UUID string identifying this bot session.
        """
        if self._context is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        bot_id = str(uuid.uuid4())
        page = await self._context.new_page()
        self._pages[bot_id] = page

        logger.info("Navigating to %s (bot=%s)", meeting_url, bot_id)
        await page.goto(meeting_url, wait_until="domcontentloaded", timeout=30_000)

        # Wait for Meet to load
        await page.wait_for_timeout(3000)

        # Enter display name if prompted (non-logged-in or guest mode)
        name_input = page.locator(_SEL_NAME_INPUT)
        if await name_input.count() > 0:
            await name_input.first.fill(bot_name)
            logger.info("Entered bot name: %s", bot_name)

        # Turn camera OFF if it's on
        try:
            camera_btn = page.locator(_SEL_CAMERA_OFF)
            if await camera_btn.count() == 0:
                # Camera is ON — find and click the camera toggle
                camera_toggle = page.locator('[aria-label*="カメラ"], [aria-label*="camera"]').first
                if await camera_toggle.count() > 0:
                    await camera_toggle.click()
                    logger.info("Camera turned off")
        except Exception:
            logger.debug("Camera toggle not found, skipping")

        # Click "Join now" or "Ask to join"
        joined = False
        for selector in [_SEL_JOIN_BTN, _SEL_ASK_JOIN]:
            btn = page.locator(selector)
            if await btn.count() > 0:
                await btn.first.click()
                logger.info("Clicked join button (bot=%s)", bot_id)
                joined = True
                break

        if not joined:
            logger.warning("No join button found, attempting to proceed (bot=%s)", bot_id)

        # Wait for admission (up to 60 seconds)
        try:
            await page.wait_for_selector(
                _SEL_IN_MEETING,
                timeout=60_000,
                state="attached",
            )
            logger.info("Successfully joined meeting (bot=%s)", bot_id)
        except Exception:
            # Even if selector not found, the bot may still be in the meeting
            logger.warning("Meeting join confirmation timeout, may still be in meeting (bot=%s)", bot_id)

        return bot_id

    async def leave_meeting(self, bot_id: str) -> None:
        """Leave the meeting and close the page for the given bot_id."""
        page = self._pages.pop(bot_id, None)
        if page is None:
            logger.warning("No page found for bot %s", bot_id)
            return

        try:
            # Try clicking the leave button
            leave_btn = page.locator(_SEL_LEAVE_BTN)
            if await leave_btn.count() > 0:
                await leave_btn.first.click()
                await page.wait_for_timeout(500)

                # Click "Leave call" in confirmation dialog if present
                end_btn = page.locator(_SEL_END_FOR_ALL)
                if await end_btn.count() > 0:
                    await end_btn.first.click()

            logger.info("Left meeting (bot=%s)", bot_id)
        except Exception:
            logger.warning("Error clicking leave button (bot=%s)", bot_id, exc_info=True)
        finally:
            try:
                await page.close()
            except Exception:
                logger.debug("Page close error (bot=%s)", bot_id, exc_info=True)

    async def shutdown(self) -> None:
        """Close all pages and shut down the browser."""
        for bot_id in list(self._pages):
            await self.leave_meeting(bot_id)

        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                logger.debug("Context close error", exc_info=True)
            self._context = None

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                logger.debug("Browser close error", exc_info=True)
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("Playwright stop error", exc_info=True)
            self._playwright = None

        logger.info("Browser client shut down")

    @property
    def active_bots(self) -> list[str]:
        """Return list of active bot IDs."""
        return list(self._pages.keys())
