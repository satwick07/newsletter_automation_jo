"""
NSE Daily Newsletter Agent - Main Orchestrator

Usage:
    python main.py                          # Full 1st cut (6:30 AM) - fetch, screenshot, PDF, Telegram
    python main.py --mode morning-brief     # Morning Brief (8:00 AM) - concise summary only
    python main.py --mode final-cut         # Final Cut (9:00 AM) - delta articles since 1st cut
    python main.py --skip-screenshots       # Skip screenshots (faster, text-only PDF)
    python main.py --dry-run                # Generate PDF but don't send Telegram

Modes:
- first-cut (default): Full pipeline — fetch, filter, screenshot, PDF, Telegram
- morning-brief: Text-only summary of the 1st cut stories sent to Telegram
- final-cut: New articles since 1st cut — screenshot, PDF, Telegram
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
from src.morning_brief import MorningBrief
from src.final_cut import FinalCut


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
    parser.add_argument("--mode", choices=["first-cut", "morning-brief", "final-cut"],
                       default="first-cut",
                       help="Run mode: first-cut (default), morning-brief, final-cut")
    parser.add_argument("--dry-run", action="store_true",
                       help="Generate report but don't send via Telegram")
    parser.add_argument("--skip-screenshots", action="store_true",
                       help="Skip screenshot capture (faster, text-only PDF)")
    return parser.parse_args()


def run_first_cut(settings: dict, telegram: TelegramSender | None,
                  skip_screenshots: bool, dry_run: bool):
    """Run the full 1st cut pipeline."""
    logger = logging.getLogger(__name__)
    report_date = datetime.now().strftime("%d %B %Y")

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
                "No news articles found for today's 1st cut report."
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

    # Step 2b: Save state for morning brief and final cut
    brief = MorningBrief(OUTPUT_DIR)
    brief.save_articles_state(filtered_articles)

    # Step 3: Capture screenshots (optional)
    if not skip_screenshots:
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
    if not dry_run and telegram:
        logger.info("Step 5: Sending via Telegram...")
        success = telegram.send_newsletter(
            categorized_articles=filtered_articles,
            pdf_path=pdf_path,
            report_date=report_date
        )
        if success:
            logger.info("1st Cut newsletter sent successfully!")
        else:
            logger.warning("1st Cut sent with some failures")
    else:
        logger.info("Step 5: Skipping Telegram send (--dry-run)")

    # Step 6: Cleanup old reports
    logger.info("Step 6: Cleaning up old reports...")
    cleaner = Cleanup(
        output_dir=OUTPUT_DIR,
        retention_days=report_settings["retention_days"]
    )
    cleaner.cleanup_old_reports()


def run_morning_brief(settings: dict, telegram: TelegramSender | None, dry_run: bool):
    """Run the morning brief — concise headline summary."""
    logger = logging.getLogger(__name__)

    brief = MorningBrief(OUTPUT_DIR)
    articles_state = brief.load_first_cut_articles()

    if not articles_state:
        logger.warning("No first cut articles found. Cannot generate morning brief.")
        if telegram:
            telegram.send_error_notification(
                "Morning Brief failed: No 1st cut data found. "
                "Ensure the 1st cut ran at 6:30 AM."
            )
        return

    # Generate concise brief text
    brief_text = brief.generate_brief(articles_state)
    logger.info(f"Morning brief generated ({len(brief_text)} chars)")

    if not dry_run and telegram:
        # Split into chunks if too long
        max_len = settings["telegram"]["max_message_length"]
        if len(brief_text) <= max_len:
            telegram._send_message(brief_text)
        else:
            # Split by category sections
            chunks = []
            current = ""
            for line in brief_text.split("\n"):
                if len(current) + len(line) + 1 > max_len:
                    chunks.append(current)
                    current = line
                else:
                    current += "\n" + line if current else line
            if current:
                chunks.append(current)

            for chunk in chunks:
                telegram._send_message(chunk)

        logger.info("Morning brief sent to Telegram!")
    else:
        logger.info("Morning brief (dry-run):")
        logger.info(brief_text[:500])


def run_final_cut(settings: dict, telegram: TelegramSender | None,
                  skip_screenshots: bool, dry_run: bool):
    """Run the final cut — delta articles since the 1st cut."""
    logger = logging.getLogger(__name__)
    report_date = datetime.now().strftime("%d %B %Y")

    # Fetch delta
    logger.info("Step 1: Fetching delta articles since 1st cut...")
    final = FinalCut(CONFIG_DIR, OUTPUT_DIR)
    delta_articles = final.fetch_delta(settings["news_fetch"])

    total_new = sum(len(arts) for arts in delta_articles.values())
    logger.info(f"Found {total_new} new articles since 1st cut")

    if total_new == 0:
        logger.info("No new articles since 1st cut. Nothing to send.")
        if telegram and not dry_run:
            telegram._send_message(
                f"<b>NSE Final Cut - {report_date}</b>\n\n"
                "<i>No additional coverages since the morning 1st cut.</i>"
            )
        return

    # Screenshots
    if not skip_screenshots:
        logger.info("Step 2: Capturing screenshots for new articles...")
        screenshot_settings = settings["screenshot"]
        capturer = ScreenshotCapture(
            output_dir=OUTPUT_DIR,
            viewport_width=screenshot_settings["viewport_width"],
            viewport_height=screenshot_settings["viewport_height"],
            page_timeout=screenshot_settings["page_timeout"],
            wait_after_load=screenshot_settings["wait_after_load"]
        )
        delta_articles = capturer.capture_all(delta_articles)

    # Build PDF
    logger.info("Step 3: Building Final Cut PDF...")
    builder = ReportBuilder(
        output_dir=OUTPUT_DIR,
        title_prefix="NSE Daily News Update - Final Cut"
    )
    pdf_path = builder.build_report(delta_articles)
    logger.info(f"Final Cut PDF generated: {pdf_path}")

    # Send via Telegram
    if not dry_run and telegram:
        logger.info("Step 4: Sending Final Cut via Telegram...")
        telegram.send_newsletter(
            categorized_articles=delta_articles,
            pdf_path=pdf_path,
            report_date=f"{report_date} (Final Cut)"
        )
        logger.info("Final Cut sent!")


def main():
    """Main orchestrator."""
    args = parse_args()

    # Setup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info(f"NSE Daily Newsletter Agent - Mode: {args.mode}")
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

    telegram = None
    if not args.dry_run:
        telegram = TelegramSender(
            bot_token=bot_token,
            chat_id=chat_id,
            max_message_length=settings["telegram"]["max_message_length"]
        )

    try:
        if args.mode == "first-cut":
            run_first_cut(settings, telegram, args.skip_screenshots, args.dry_run)
        elif args.mode == "morning-brief":
            run_morning_brief(settings, telegram, args.dry_run)
        elif args.mode == "final-cut":
            run_final_cut(settings, telegram, args.skip_screenshots, args.dry_run)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        if telegram:
            telegram.send_error_notification(f"Pipeline failed ({args.mode}): {str(e)}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("NSE Daily Newsletter Agent - Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
