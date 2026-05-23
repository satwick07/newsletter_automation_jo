"""
Cleanup Module
Removes reports and screenshots older than the configured retention period.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class Cleanup:
    """Handles cleanup of old reports and screenshots."""

    def __init__(self, output_dir: Path, retention_days: int = 7):
        self.output_dir = output_dir
        self.retention_days = retention_days

    def cleanup_old_reports(self) -> int:
        """
        Remove report files and screenshot directories older than retention_days.
        Returns the number of items removed.
        """
        if not self.output_dir.exists():
            logger.info("Output directory does not exist, nothing to clean")
            return 0

        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        removed_count = 0

        # Clean PDF files
        for pdf_file in self.output_dir.glob("*.pdf"):
            file_mtime = datetime.fromtimestamp(pdf_file.stat().st_mtime)
            if file_mtime < cutoff_date:
                try:
                    pdf_file.unlink()
                    logger.info(f"Removed old report: {pdf_file.name}")
                    removed_count += 1
                except OSError as e:
                    logger.warning(f"Failed to remove {pdf_file}: {e}")

        # Clean HTML files
        for html_file in self.output_dir.glob("*.html"):
            file_mtime = datetime.fromtimestamp(html_file.stat().st_mtime)
            if file_mtime < cutoff_date:
                try:
                    html_file.unlink()
                    logger.info(f"Removed old HTML: {html_file.name}")
                    removed_count += 1
                except OSError as e:
                    logger.warning(f"Failed to remove {html_file}: {e}")

        # Clean screenshot directories
        screenshots_dir = self.output_dir / "screenshots"
        if screenshots_dir.exists():
            for screenshot in screenshots_dir.glob("*.png"):
                file_mtime = datetime.fromtimestamp(screenshot.stat().st_mtime)
                if file_mtime < cutoff_date:
                    try:
                        screenshot.unlink()
                        logger.info(f"Removed old screenshot: {screenshot.name}")
                        removed_count += 1
                    except OSError as e:
                        logger.warning(f"Failed to remove {screenshot}: {e}")

        logger.info(
            f"Cleanup complete: {removed_count} items removed "
            f"(retention: {self.retention_days} days)"
        )
        return removed_count
