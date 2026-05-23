"""
Screenshot Capture Module
Uses Playwright to capture above-the-fold screenshots of article pages.
Implements anti-detection measures to avoid being flagged as a bot.
"""

import asyncio
import logging
import random
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# Max concurrent screenshot tabs (keep low to avoid detection)
MAX_CONCURRENT = 3

# Realistic user agents (rotated per page)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


class ScreenshotCapture:
    """Captures above-the-fold screenshots of article URLs using Playwright with stealth."""

    def __init__(self, output_dir: Path, viewport_width: int = 1280,
                 viewport_height: int = 900, page_timeout: int = 20,
                 wait_after_load: int = 2):
        self.output_dir = output_dir
        self.screenshots_dir = output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.page_timeout = page_timeout * 1000
        self.wait_after_load = wait_after_load * 1000

    def _sanitize_filename(self, text: str, max_length: int = 60) -> str:
        """Create a safe filename from headline text."""
        safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in text)
        safe = safe.strip().replace(" ", "_")[:max_length]
        return safe or "article"

    async def _stealth_setup(self, page):
        """Apply stealth techniques to avoid bot detection."""
        # Override navigator.webdriver to return false
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'hi']});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({query: (params) => Promise.resolve({state: 'granted'})})
            });
        """)

    async def _capture_single(self, context, url: str, filename: str,
                              semaphore: asyncio.Semaphore) -> str | None:
        """Capture a single screenshot with anti-detection delays."""
        screenshot_path = self.screenshots_dir / f"{filename}.png"

        async with semaphore:
            # Random delay between 1-3 seconds before each capture (mimics human)
            await asyncio.sleep(random.uniform(1.0, 3.0))

            page = await context.new_page()
            await self._stealth_setup(page)

            try:
                # Navigate with networkidle for better content loading
                await page.goto(url, wait_until="domcontentloaded",
                              timeout=self.page_timeout)

                # Human-like wait (random 1.5-3s)
                await page.wait_for_timeout(random.randint(1500, 3000))

                # Simulate minimal scroll (human behavior)
                await page.evaluate("window.scrollBy(0, 100)")
                await page.wait_for_timeout(300)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)

                # Quick popup dismiss
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
            "button:has-text('Accept All')",
            "button:has-text('Got it')",
            "button:has-text('I Agree')",
            "[class*='cookie'] button",
            "[class*='consent'] button",
            "[class*='gdpr'] button",
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
        Capture screenshots for all articles using parallel tabs with stealth.
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
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ]
            )

            # Randomize user agent per session
            ua = random.choice(USER_AGENTS)

            context = await browser.new_context(
                viewport={
                    "width": self.viewport_width,
                    "height": self.viewport_height
                },
                user_agent=ua,
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                # Appear as real browser
                java_script_enabled=True,
                has_touch=False,
                is_mobile=False,
                color_scheme="light",
            )

            # Block unnecessary resources to speed up + reduce fingerprint
            await context.route("**/*.{mp4,webm,ogg,wav,mp3}", lambda route: route.abort())
            await context.route("**/ads/**", lambda route: route.abort())
            await context.route("**/analytics/**", lambda route: route.abort())
            await context.route("**/tracking/**", lambda route: route.abort())

            # Launch captures with bounded concurrency
            tasks = []
            for i, article in enumerate(articles):
                filename = f"{i+1:03d}_{self._sanitize_filename(article.headline)}"
                task = self._capture_single(context, article.url, filename, semaphore)
                tasks.append((article, task))

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
        """
        all_articles = []
        for category_articles in categorized_articles.values():
            all_articles.extend(category_articles)

        logger.info(f"Capturing {len(all_articles)} screenshots (parallel={MAX_CONCURRENT}, stealth=on)...")

        try:
            asyncio.run(self.capture_articles(all_articles))
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")

        return categorized_articles
