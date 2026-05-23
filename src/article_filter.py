"""
Article Filter Module
Filters and deduplicates articles based on publication whitelist,
relevance scoring, and category rules.
"""

import json
import logging
from difflib import SequenceMatcher
from pathlib import Path

from .news_fetcher import Article

logger = logging.getLogger(__name__)


class ArticleFilter:
    """Filters and ranks articles based on relevance and publication rules."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        with open(config_dir / "publications.json", "r", encoding="utf-8") as f:
            self.publications = json.load(f)
        with open(config_dir / "keywords.json", "r", encoding="utf-8") as f:
            self.keywords = json.load(f)

    def _headline_similarity(self, h1: str, h2: str) -> float:
        """Calculate similarity ratio between two headlines."""
        return SequenceMatcher(None, h1.lower(), h2.lower()).ratio()

    def deduplicate(self, articles: list[Article],
                    similarity_threshold: float = 0.75) -> list[Article]:
        """
        Remove near-duplicate articles (same story from different publications).
        Keeps the first occurrence (usually from a higher-priority publication).
        """
        unique = []
        for article in articles:
            is_duplicate = False
            for existing in unique:
                if self._headline_similarity(
                    article.headline, existing.headline
                ) > similarity_threshold:
                    is_duplicate = True
                    logger.debug(
                        f"Duplicate removed: '{article.headline}' "
                        f"(similar to '{existing.headline}')"
                    )
                    break
            if not is_duplicate:
                unique.append(article)
        return unique

    def _get_publication_priority(self, publication: str) -> int:
        """
        Assign priority score to a publication.
        Lower = higher priority (financial > online > regional).
        """
        pub_lower = publication.lower().strip()

        # Priority order: financial > wires > online > international > print > regional > tv > magazines
        priority_map = {
            "financial": 1,
            "wires": 2,
            "online": 3,
            "international": 4,
            "print": 5,
            "regional": 6,
            "tv_channels": 7,
            "magazines": 8
        }

        for category, pubs in self.publications.items():
            for pub in pubs:
                if pub.lower().strip() in pub_lower or pub_lower in pub.lower().strip():
                    return priority_map.get(category, 9)

        return 10  # Unknown publication

    def rank_articles(self, articles: list[Article]) -> list[Article]:
        """Sort articles by publication priority (higher priority first)."""
        return sorted(
            articles,
            key=lambda a: self._get_publication_priority(a.publication)
        )

    def filter_category(self, articles: list[Article], category: str,
                        max_articles: int = 15) -> list[Article]:
        """
        Apply category-specific filtering rules.
        """
        category_data = self.keywords.get("categories", {}).get(category, {})
        rules = category_data.get("rules", "")

        # For "Corporate" and "Others" - only trending/breaking stories
        # We use a simple heuristic: prioritize articles from top-tier publications
        if category in ("Corporate", "Others"):
            articles = self.rank_articles(articles)
            # Be more selective - take fewer articles
            max_articles = min(max_articles, 8)

        # Deduplicate within category
        articles = self.deduplicate(articles)

        # Rank and trim
        articles = self.rank_articles(articles)
        return articles[:max_articles]

    def filter_all(self, categorized_articles: dict[str, list[Article]],
                   max_total: int = 50) -> dict[str, list[Article]]:
        """
        Apply filtering to all categories.
        Returns cleaned, deduplicated, and ranked articles per category.
        """
        filtered = {}
        total_count = 0

        for category, articles in categorized_articles.items():
            remaining_budget = max_total - total_count
            if remaining_budget <= 0:
                filtered[category] = []
                continue

            max_for_category = min(15, remaining_budget)
            filtered_articles = self.filter_category(
                articles, category, max_articles=max_for_category
            )
            filtered[category] = filtered_articles
            total_count += len(filtered_articles)

            logger.info(
                f"Category '{category}': {len(articles)} -> "
                f"{len(filtered_articles)} articles after filtering"
            )

        logger.info(f"Total articles after filtering: {total_count}")
        return filtered
