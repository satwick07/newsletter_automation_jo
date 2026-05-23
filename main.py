"""
NSE Daily Newsletter Agent - Main Orchestrator

Usage:
    python main.py                  # Full run (fetch, screenshot, PDF, Telegram)
    python main.py --skip-screenshots  # Skip screenshots (faster, text-only PDF)
    python main.py --dry-run        # Generate PDF but don't send Telegram
    python main.py --skip-screenshots --dry-run  # Fastest test

Workflow:
1. Load configuration
2. Fetch news articles via Google News (filtered by keywords)
3. Filter and deduplicate articles
4. Capture above-the-fold screenshots (optional)
5. Build PDF report
6. Send via Telegram (inline summary + PDF)
7. Cleanup old reports
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = Path(__file__).parent
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Add src to path
sys.path.insert(0, str(PROJECT_ROOT))

from src.news_fetcher import NewsFetcher
from src.article_filter import ArticleFilter
from src.screenshot_capture import ScreenshotCapture
from src.report_builder import ReportBuilder
from src.telegram_sender import TelegramSender
from src.cleanup import Cleanup


def setup_logging():
    """Configure logging for the application."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"newsletter_{date_str}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )


def load_settings() -> dict:
    """Load settings from YAML config."""
    settings_path = CONFIG_DIR / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="NSE Daily Newsletter Agent")
    parser.add_argument("--dry-run", action="store_true",
                       help="Generate report but don't send via Telegram")
    parser.add_argument("--skip-screenshots", action="store_true",
                       help="Skip screenshot capture (faster, text-only PDF)")
    return parser.parse_args()


def main():
    """Main orchestrator - runs the full newsletter pipeline."""
    args = parse_args()

    # Setup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("NSE Daily Newsletter Agent - Starting")
    logger.info(f"  dry_run={args.dry_run}, skip_screenshots={args.skip_screenshots}")
    logger.info("=" * 60)

    # Load environment variables
    load_dotenv(PROJECT_ROOT / ".env")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not args.dry_run and (not bot_token or not chat_id):
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    # Load settings
    settings = load_settings()
    report_date = datetime.now().strftime("%d %B %Y")

    telegram = None
    if not args.dry_run:
        telegram = TelegramSender(
            bot_token=bot_token,
            chat_id=chat_id,
            max_message_length=settings["telegram"]["max_message_length"]
        )

    try:
        # Step 1: Fetch news
        logger.info("Step 1: Fetching news articles...")
        fetcher = NewsFetcher(CONFIG_DIR)
        raw_articles = fetcher.fetch_all(settings["news_fetch"])

        total_raw = sum(len(arts) for arts in raw_articles.values())
        logger.info(f"Fetched {total_raw} raw articles across all categories")

        if total_raw == 0:
            logger.warning("No articles found.")
            if telegram:
                telegram.send_error_notification(
                    "No news articles found for today's report. "
                    "This may indicate a scraping issue."
                )
            return

        # Step 2: Filter and deduplicate
        logger.info("Step 2: Filtering and deduplicating articles...")
        article_filter = ArticleFilter(CONFIG_DIR)
        filtered_articles = article_filter.filter_all(
            raw_articles,
            max_total=settings["news_fetch"]["max_total_articles"]
        )

        total_filtered = sum(len(arts) for arts in filtered_articles.values())
        logger.info(f"After filtering: {total_filtered} articles")

        # Step 3: Capture screenshots (optional)
        if not args.skip_screenshots:
            logger.info("Step 3: Capturing screenshots...")
            screenshot_settings = settings["screenshot"]
            capturer = ScreenshotCapture(
                output_dir=OUTPUT_DIR,
                viewport_width=screenshot_settings["viewport_width"],
                viewport_height=screenshot_settings["viewport_height"],
                page_timeout=screenshot_settings["page_timeout"],
                wait_after_load=screenshot_settings["wait_after_load"]
            )
            filtered_articles = capturer.capture_all(filtered_articles)
        else:
            logger.info("Step 3: Skipping screenshots (--skip-screenshots)")

        # Step 4: Build PDF report
        logger.info("Step 4: Building PDF report...")
        report_settings = settings["report"]
        builder = ReportBuilder(
            output_dir=OUTPUT_DIR,
            title_prefix=report_settings["title_prefix"]
        )
        pdf_path = builder.build_report(filtered_articles)
        logger.info(f"PDF generated: {pdf_path}")

        # Step 5: Send via Telegram
        if not args.dry_run and telegram:
            logger.info("Step 5: Sending via Telegram...")
            success = telegram.send_newsletter(
                categorized_articles=filtered_articles,
                pdf_path=pdf_path,
                report_date=report_date
            )
            if success:
                logger.info("Newsletter sent successfully!")
            else:
                logger.warning("Newsletter sent with some failures")
        else:
            logger.info("Step 5: Skipping Telegram send (--dry-run)")

        # Step 6: Cleanup old reports
        logger.info("Step 6: Cleaning up old reports...")
        cleaner = Cleanup(
            output_dir=OUTPUT_DIR,
            retention_days=report_settings["retention_days"]
        )
        removed = cleaner.cleanup_old_reports()
        logger.info(f"Cleanup: {removed} old items removed")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        if telegram:
            telegram.send_error_notification(f"Pipeline failed: {str(e)}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("NSE Daily Newsletter Agent - Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
