"""
Coverage Dossier Module
Tracks press release coverage over 7 days with 4 follow-up reports.

Schedule per dossier:
- 1st cut report: shared before 12 PM the next day of announcement
- 2nd cut report: 2 days after sharing first cut at 11 AM
- 3rd cut report: 2 days after sharing second cut at 11 AM
- 4th cut report: shared on the 7th day at 11 AM

State is persisted in dossiers.json.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher

from .news_fetcher import NewsFetcher, Article
from .article_filter import ArticleFilter

logger = logging.getLogger(__name__)


class Dossier:
    """Represents a single press release coverage dossier."""

    def __init__(self, dossier_id: str, headline: str, keywords: list[str],
                 created_at: str, source_articles: list[dict]):
        self.dossier_id = dossier_id
        self.headline = headline
        self.keywords = keywords  # Search keywords derived from headline
        self.created_at = created_at
        self.source_articles = source_articles  # Initial articles that triggered dossier
        self.follow_ups = {
            "cut_1": {"due": "", "completed": False, "articles": []},
            "cut_2": {"due": "", "completed": False, "articles": []},
            "cut_3": {"due": "", "completed": False, "articles": []},
            "cut_4": {"due": "", "completed": False, "articles": []},
        }
        self._calculate_due_dates()

    def _calculate_due_dates(self):
        """Calculate due dates for each follow-up cut."""
        created = datetime.fromisoformat(self.created_at)
        # Cut 1: next day 12 PM
        cut1_date = (created + timedelta(days=1)).replace(hour=12, minute=0, second=0)
        # Cut 2: 2 days after cut 1, 11 AM
        cut2_date = (cut1_date + timedelta(days=2)).replace(hour=11, minute=0, second=0)
        # Cut 3: 2 days after cut 2, 11 AM
        cut3_date = (cut2_date + timedelta(days=2)).replace(hour=11, minute=0, second=0)
        # Cut 4: 7th day from creation, 11 AM
        cut4_date = (created + timedelta(days=7)).replace(hour=11, minute=0, second=0)

        self.follow_ups["cut_1"]["due"] = cut1_date.isoformat()
        self.follow_ups["cut_2"]["due"] = cut2_date.isoformat()
        self.follow_ups["cut_3"]["due"] = cut3_date.isoformat()
        self.follow_ups["cut_4"]["due"] = cut4_date.isoformat()

    def is_complete(self) -> bool:
        """Check if all 4 follow-ups are done."""
        return all(cut["completed"] for cut in self.follow_ups.values())

    def get_pending_cuts(self) -> list[str]:
        """Get list of cuts that are due now."""
        now = datetime.now()
        pending = []
        for cut_name, cut_data in self.follow_ups.items():
            if cut_data["completed"]:
                continue
            due = datetime.fromisoformat(cut_data["due"])
            if now >= due:
                pending.append(cut_name)
        return pending

    def to_dict(self) -> dict:
        return {
            "dossier_id": self.dossier_id,
            "headline": self.headline,
            "keywords": self.keywords,
            "created_at": self.created_at,
            "source_articles": self.source_articles,
            "follow_ups": self.follow_ups,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Dossier":
        d = cls(
            dossier_id=data["dossier_id"],
            headline=data["headline"],
            keywords=data["keywords"],
            created_at=data["created_at"],
            source_articles=data["source_articles"]
        )
        d.follow_ups = data["follow_ups"]
        return d


class CoverageDossierManager:
    """Manages all active coverage dossiers."""

    def __init__(self, config_dir: Path, output_dir: Path):
        self.config_dir = config_dir
        self.output_dir = output_dir
        self.state_file = output_dir / "dossiers.json"
        self.dossiers = self._load_state()

    def _load_state(self) -> list[Dossier]:
        """Load active dossiers from state file."""
        if not self.state_file.exists():
            return []
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Dossier.from_dict(d) for d in data.get("active_dossiers", [])]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load dossiers state: {e}")
            return []

    def _save_state(self):
        """Persist dossiers to state file."""
        # Remove completed dossiers
        active = [d for d in self.dossiers if not d.is_complete()]
        data = {
            "last_updated": datetime.now().isoformat(),
            "active_dossiers": [d.to_dict() for d in active]
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(active)} active dossiers to state")

    def _extract_keywords(self, headline: str) -> list[str]:
        """Extract search keywords from a press release headline."""
        # Remove common filler words and extract key terms
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
            "to", "for", "of", "and", "or", "by", "with", "from", "its",
            "has", "have", "had", "will", "be", "been", "being", "says",
            "said", "new", "that", "this", "it", "as", "up", "out"
        }
        words = headline.replace(",", "").replace(":", "").replace("-", " ").split()
        keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        # Take top 5-6 significant words as search phrase
        key_phrase = " ".join(keywords[:6])
        return [key_phrase, " ".join(keywords[:3])]

    def _is_press_release(self, articles: list, threshold: int = 3) -> tuple[bool, list]:
        """
        Detect if a set of articles represents a press release.
        A press release = same/similar headline appearing in 3+ publications.
        Returns (is_pr, grouped_articles).
        """
        # Group articles by headline similarity
        groups = []
        for article in articles:
            placed = False
            headline = article.headline if hasattr(article, 'headline') else article.get("headline", "")
            for group in groups:
                ref_headline = group[0].headline if hasattr(group[0], 'headline') else group[0].get("headline", "")
                similarity = SequenceMatcher(None, headline.lower(), ref_headline.lower()).ratio()
                if similarity > 0.6:
                    group.append(article)
                    placed = True
                    break
            if not placed:
                groups.append([article])

        # Find groups with 3+ articles (press release indicator)
        pr_groups = [g for g in groups if len(g) >= threshold]
        return len(pr_groups) > 0, pr_groups

    def detect_and_create_dossiers(self, categorized_articles: dict):
        """
        Scan today's articles for press releases and create dossiers.
        Called after the 1st cut pipeline.
        """
        all_articles = []
        for articles in categorized_articles.values():
            for article in articles:
                if hasattr(article, 'to_dict'):
                    all_articles.append(article)
                else:
                    all_articles.append(article)

        is_pr, pr_groups = self._is_press_release(all_articles)

        if not is_pr:
            logger.info("No press releases detected today.")
            return

        for group in pr_groups:
            # Get headline from first article
            first = group[0]
            headline = first.headline if hasattr(first, 'headline') else first.get("headline", "")

            # Check if we already have a dossier for this
            existing = any(
                SequenceMatcher(None, d.headline.lower(), headline.lower()).ratio() > 0.7
                for d in self.dossiers
            )
            if existing:
                logger.info(f"Dossier already exists for: {headline[:60]}")
                continue

            # Create new dossier
            dossier_id = f"dossier_{datetime.now().strftime('%Y%m%d_%H%M')}_{len(self.dossiers)}"
            keywords = self._extract_keywords(headline)
            source_articles = []
            for a in group:
                if hasattr(a, 'to_dict'):
                    source_articles.append(a.to_dict())
                else:
                    source_articles.append(a)

            dossier = Dossier(
                dossier_id=dossier_id,
                headline=headline,
                keywords=keywords,
                created_at=datetime.now().isoformat(),
                source_articles=source_articles
            )
            self.dossiers.append(dossier)
            logger.info(f"Created dossier: {headline[:60]} ({len(group)} initial articles)")

        self._save_state()

    def process_pending_follow_ups(self) -> list[dict]:
        """
        Check all active dossiers for pending follow-up cuts.
        Fetches new coverage and returns reports to send.
        Returns list of {dossier, cut_name, articles} dicts.
        """
        if not self.dossiers:
            logger.info("No active dossiers to process.")
            return []

        fetcher = NewsFetcher(self.config_dir)
        reports = []

        for dossier in self.dossiers:
            pending_cuts = dossier.get_pending_cuts()
            if not pending_cuts:
                continue

            # Search for new coverage using dossier keywords
            logger.info(f"Processing dossier: {dossier.headline[:50]} - cuts: {pending_cuts}")

            all_found_articles = []
            for keyword in dossier.keywords:
                from urllib.parse import quote_plus
                import requests
                from bs4 import BeautifulSoup

                rss_url = f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl=en-IN&gl=IN&ceid=IN:en"
                raw = fetcher._parse_rss_feed(rss_url)
                all_found_articles.extend(raw)

            # Deduplicate against already-known articles
            known_urls = set()
            for a in dossier.source_articles:
                known_urls.add(a.get("url", ""))
            for cut_data in dossier.follow_ups.values():
                for a in cut_data.get("articles", []):
                    known_urls.add(a.get("url", ""))

            new_articles = [
                a for a in all_found_articles
                if a.get("url", "") and a["url"] not in known_urls
            ]

            # Mark all pending cuts as completed
            for cut_name in pending_cuts:
                dossier.follow_ups[cut_name]["completed"] = True
                dossier.follow_ups[cut_name]["articles"] = new_articles
                dossier.follow_ups[cut_name]["completed_at"] = datetime.now().isoformat()

            if new_articles or pending_cuts:
                reports.append({
                    "dossier": dossier,
                    "cut_names": pending_cuts,
                    "new_articles": new_articles,
                    "total_coverage": (
                        len(dossier.source_articles) +
                        sum(len(c["articles"]) for c in dossier.follow_ups.values())
                    )
                })

        self._save_state()
        return reports

    def format_dossier_report(self, report: dict) -> str:
        """Format a dossier follow-up report as Telegram HTML message."""
        dossier = report["dossier"]
        cuts = ", ".join(report["cut_names"]).replace("cut_", "Cut ")
        new_count = len(report["new_articles"])
        total = report["total_coverage"]

        lines = [
            f"<b>📋 Coverage Dossier - {cuts}</b>",
            f"<b>PR:</b> {dossier.headline[:80]}",
            f"<b>Created:</b> {dossier.created_at[:10]}",
            f"<b>Total coverage:</b> {total} articles",
            f"<b>New since last cut:</b> {new_count} articles",
            ""
        ]

        if report["new_articles"]:
            lines.append("<b>New Coverage:</b>")
            for i, article in enumerate(report["new_articles"][:15], 1):
                headline = article.get("headline", "")[:70]
                pub = article.get("publication", "Unknown")
                url = article.get("url", "")
                lines.append(f'{i}. <a href="{url}">{headline}</a> <i>({pub})</i>')
        else:
            lines.append("<i>No new coverage found since last cut.</i>")

        # Show completion status
        lines.append("")
        lines.append("<b>Status:</b>")
        for cut_name, cut_data in dossier.follow_ups.items():
            status = "✅" if cut_data["completed"] else "⏳"
            due = cut_data["due"][:10] if cut_data["due"] else "TBD"
            lines.append(f"  {status} {cut_name.replace('_', ' ').title()} (due: {due})")

        return "\n".join(lines)
