"""
News Fetcher Module
Searches Google News for articles matching configured keywords.
Returns structured article data (headline, URL, publication, timestamp).
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

GOOGLE_NEWS_URL = "https://news.google.com/search"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

# User agent to avoid blocking
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class Article:
    """Represents a single news article."""

    def __init__(self, headline: str, url: str, publication: str,
                 published_date: str = "", category: str = ""):
        self.headline = headline
        self.url = url
        self.publication = publication
        self.published_date = published_date
        self.category = category
        self.screenshot_path = None

    def to_dict(self):
        return {
            "headline": self.headline,
            "url": self.url,
            "publication": self.publication,
            "published_date": self.published_date,
            "category": self.category,
            "screenshot_path": self.screenshot_path
        }


class NewsFetcher:
    """Fetches news articles from Google News RSS based on keywords."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.keywords = self._load_keywords()
        self.publications = self._load_publications()
        self._all_publications = self._flatten_publications()
        self._global_excludes = [
            kw.lower() for kw in self.keywords.get("global_exclude_keywords", [])
        ]

    def _load_keywords(self) -> dict:
        keywords_path = self.config_dir / "keywords.json"
        with open(keywords_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_publications(self) -> dict:
        publications_path = self.config_dir / "publications.json"
        with open(publications_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _flatten_publications(self) -> set:
        """Flatten all publication lists into a single set for quick lookup."""
        all_pubs = set()
        for category_pubs in self.publications.values():
            for pub in category_pubs:
                all_pubs.add(pub.lower().strip())
        return all_pubs

    def _build_search_query(self, keyword: str, hours_back: int = 24) -> str:
        """Build a Google News RSS search query URL."""
        # Use 'when' parameter for time filtering
        query = quote_plus(keyword)
        url = (
            f"{GOOGLE_NEWS_RSS}?q={query}"
            f"&hl=en-IN&gl=IN&ceid=IN:en"
        )
        return url

    def _parse_rss_feed(self, rss_url: str) -> list[dict]:
        """Parse Google News RSS feed and extract articles."""
        articles = []
        try:
            response = requests.get(rss_url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "xml")
            items = soup.find_all("item")

            for item in items:
                title = item.find("title")
                pub_date = item.find("pubDate")
                source = item.find("source")

                # Google News RSS puts URL as text node after <link/> tag
                link_tag = item.find("link")
                url = ""
                if link_tag:
                    # Try getting text content first
                    url = link_tag.get_text(strip=True)
                    # If empty, get the next sibling text node
                    if not url and link_tag.next_sibling:
                        url = str(link_tag.next_sibling).strip()
                    # If source tag has url attribute, use that
                    if not url and source and source.get("url"):
                        url = source["url"]

                if title and url:
                    articles.append({
                        "headline": title.get_text(strip=True),
                        "url": url,
                        "publication": source.get_text(strip=True) if source else "Unknown",
                        "published_date": pub_date.get_text(strip=True) if pub_date else ""
                    })
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch RSS feed {rss_url}: {e}")
        except Exception as e:
            logger.warning(f"Error parsing RSS feed: {e}")

        return articles

    def _is_within_timeframe(self, pub_date_str: str, hours_back: int) -> bool:
        """Check if article was published within the lookback window."""
        if not pub_date_str:
            return True  # Include if no date available (assume recent)

        try:
            from email.utils import parsedate_to_datetime
            pub_date = parsedate_to_datetime(pub_date_str)
            cutoff = datetime.now(pub_date.tzinfo) - timedelta(hours=hours_back)
            return pub_date >= cutoff
        except (ValueError, TypeError):
            return True  # Include if date can't be parsed

    def _is_known_publication(self, publication: str) -> bool:
        """Check if the publication is in our whitelist."""
        pub_lower = publication.lower().strip()
        # Check for partial match (e.g., "The Economic Times" matches "Economic Times")
        for known_pub in self._all_publications:
            if known_pub in pub_lower or pub_lower in known_pub:
                return True
        return False

    def _is_excluded(self, headline: str, category_excludes: list = None) -> bool:
        """Check if headline contains any excluded keywords (global + category)."""
        headline_lower = headline.lower()
        # Check global excludes
        for excl in self._global_excludes:
            if excl in headline_lower:
                logger.debug(f"Excluded (global '{excl}'): {headline}")
                return True
        # Check category-specific excludes
        if category_excludes:
            for excl in category_excludes:
                if excl.lower() in headline_lower:
                    logger.debug(f"Excluded (category '{excl}'): {headline}")
                    return True
        return False

    def fetch_news(self, hours_back: int = 24,
                   max_per_category: int = 15) -> dict[str, list[Article]]:
        """
        Fetch news articles for all categories.
        Returns dict: {category_name: [Article, ...]}
        """
        results = {}
        categories = self.keywords.get("categories", {})
        seen_urls = set()

        for category_name, category_data in categories.items():
            category_articles = []
            keywords = category_data.get("keywords", [])
            category_excludes = category_data.get("exclude_keywords", [])

            logger.info(f"Fetching news for category: {category_name} "
                       f"({len(keywords)} keywords)")

            for keyword in keywords:
                rss_url = self._build_search_query(keyword, hours_back)
                raw_articles = self._parse_rss_feed(rss_url)

                for raw in raw_articles:
                    # Skip duplicates
                    if raw["url"] in seen_urls:
                        continue

                    # Check timeframe
                    if not self._is_within_timeframe(raw["published_date"], hours_back):
                        continue

                    # Check if publication is in our whitelist
                    if not self._is_known_publication(raw["publication"]):
                        continue

                    # Check exclude keywords (global + category-specific)
                    if self._is_excluded(raw["headline"], category_excludes):
                        continue

                    seen_urls.add(raw["url"])
                    article = Article(
                        headline=raw["headline"],
                        url=raw["url"],
                        publication=raw["publication"],
                        published_date=raw["published_date"],
                        category=category_name
                    )
                    category_articles.append(article)

                    if len(category_articles) >= max_per_category:
                        break

                # Rate limiting - be respectful to Google
                time.sleep(0.5)

                if len(category_articles) >= max_per_category:
                    break

            results[category_name] = category_articles
            logger.info(f"  Found {len(category_articles)} articles for {category_name}")

        return results

    def fetch_all(self, settings: dict) -> dict[str, list[Article]]:
        """
        Main entry point - fetch all news based on settings.
        Handles Monday lookback logic automatically.
        """
        now = datetime.now()
        is_monday = now.weekday() == 0

        hours_back = (
            settings.get("monday_lookback_hours", 70)
            if is_monday
            else settings.get("lookback_hours", 24)
        )
        max_per_category = settings.get("max_articles_per_category", 15)

        logger.info(f"Fetching news - lookback: {hours_back}h, "
                   f"max/category: {max_per_category}, "
                   f"is_monday: {is_monday}")

        return self.fetch_news(hours_back=hours_back,
                              max_per_category=max_per_category)
