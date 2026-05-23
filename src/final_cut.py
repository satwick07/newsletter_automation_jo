"""
Final Cut Module
Fetches articles that appeared AFTER the morning 1st cut.
Only includes new articles not already in the first cut report.
"""

import json
import logging
from pathlib import Path

from .news_fetcher import NewsFetcher, Article
from .article_filter import ArticleFilter

logger = logging.getLogger(__name__)


class FinalCut:
    """Generates the final cut by finding delta articles since the 1st cut."""

    def __init__(self, config_dir: Path, output_dir: Path):
        self.config_dir = config_dir
        self.output_dir = output_dir
        self.state_file = output_dir / "last_run_articles.json"

    def _load_first_cut_urls(self) -> set:
        """Load URLs from the first cut to identify what's already been reported."""
        if not self.state_file.exists():
            logger.warning("No first cut state file found.")
            return set()

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        urls = set()
        for category_articles in state.values():
            for article in category_articles:
                url = article.get("url", "")
                if url:
                    urls.add(url)

        logger.info(f"Loaded {len(urls)} URLs from first cut")
        return urls

    def fetch_delta(self, settings: dict) -> dict[str, list[Article]]:
        """
        Fetch current news and return only articles NOT in the first cut.
        """
        first_cut_urls = self._load_first_cut_urls()

        # Fetch fresh articles
        fetcher = NewsFetcher(self.config_dir)
        # Use shorter lookback for final cut (just since morning)
        fetch_settings = settings.copy()
        fetch_settings["lookback_hours"] = 6  # Only last 6 hours
        raw_articles = fetcher.fetch_all(fetch_settings)

        # Filter out articles already in first cut
        delta = {}
        for category, articles in raw_articles.items():
            new_articles = [
                a for a in articles if a.url not in first_cut_urls
            ]
            delta[category] = new_articles

        total_new = sum(len(a) for a in delta.values())
        logger.info(f"Final cut delta: {total_new} new articles since first cut")

        # Apply standard filters
        if total_new > 0:
            article_filter = ArticleFilter(self.config_dir)
            delta = article_filter.filter_all(delta, max_total=20)

        return delta
