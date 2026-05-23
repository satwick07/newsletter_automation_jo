"""
Screenshot Capture Module
Uses Playwright to capture above-the-fold screenshots of article pages.
Runs multiple tabs concurrently for speed.
"""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# Max concurrent screenshot tabs
MAX_CONCURRENT = 4


class ScreenshotCapture:
    """Captures above-the-fold screenshots of article URLs using Playwright."""

    def __init__(self, output_dir: Path, viewport_width: int = 1280,
                 viewport_height: int = 900, page_timeout: int = 20,
                 wait_after_load: int = 1):
        self.output_dir = output_dir
        self.screenshots_dir = output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.page_timeout = page_timeout * 1000  # Convert to ms
        self.wait_after_load = wait_after_load * 1000  # Convert to ms

    def _sanitize_filename(self, text: str, max_length: int = 60) -> str:
        """Create a safe filename from headline text."""
        safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in text)
        safe = safe.strip().replace(" ", "_")[:max_length]
        return safe or "article"

    async def _capture_single(self, context, url: str, filename: str,
                              semaphore: asyncio.Semaphore) -> str | None:
        """Capture a single screenshot using a new page. Returns path or None."""
        screenshot_path = self.screenshots_dir / f"{filename}.png"

        async with semaphore:
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded",
                              timeout=self.page_timeout)
                await page.wait_for_timeout(self.wait_after_load)

                # Quick popup dismiss (non-blocking, best effort)
                await self._dismiss_popups(page)

                await page.screenshot(
                    path=str(screenshot_path),
                    full_page=False,
                    type="png"
                )
                logger.debug(f"Screenshot captured: {filename}")
                return str(screenshot_path)

            except PlaywrightTimeout:
                logger.warning(f"Timeout: {url[:80]}")
                return None
            except Exception as e:
                logger.warning(f"Failed: {url[:60]} - {e}")
                return None
            finally:
                await page.close()

    async def _dismiss_popups(self, page):
        """Quick attempt to dismiss cookie/consent popups."""
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('Got it')",
            "[class*='cookie'] button",
            "[class*='consent'] button",
        ]
        for selector in selectors:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=500):
                    await el.click(timeout=1000)
                    break
            except Exception:
                continue

    async def capture_articles(self, articles: list) -> list:
        """
        Capture screenshots for all articles using parallel tabs.
        Updates each article's screenshot_path attribute.
        """
        if not articles:
            return articles

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ]
            )
            context = await browser.new_context(
                viewport={
                    "width": self.viewport_width,
                    "height": self.viewport_height
                },
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True
            )

            # Launch all captures concurrently (bounded by semaphore)
            tasks = []
            for i, article in enumerate(articles):
                filename = f"{i+1:03d}_{self._sanitize_filename(article.headline)}"
                task = self._capture_single(context, article.url, filename, semaphore)
                tasks.append((article, task))

            # Gather results
            results = await asyncio.gather(
                *[t[1] for t in tasks], return_exceptions=True
            )

            for (article, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    article.screenshot_path = None
                else:
                    article.screenshot_path = result

            await browser.close()

        captured = sum(1 for a in articles if a.screenshot_path)
        logger.info(f"Screenshots captured: {captured}/{len(articles)}")
        return articles

    def capture_all(self, categorized_articles: dict) -> dict:
        """
        Synchronous wrapper - captures screenshots for all articles.
        Returns the same dict with screenshot_path populated.
        """
        all_articles = []
        for category_articles in categorized_articles.values():
            all_articles.extend(category_articles)

        logger.info(f"Capturing {len(all_articles)} screenshots (parallel={MAX_CONCURRENT})...")

        # Run async capture
        try:
            asyncio.run(self.capture_articles(all_articles))
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            # Continue without screenshots - report will show [Screenshot unavailable]

        return categorized_articles
