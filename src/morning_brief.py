"""
Morning Brief Module
Generates a concise text-only summary of the 1st cut stories.
Sent as a Telegram message at 8 AM (no PDF).

Format:
- Category headers
- Headline + Publication (one line per article)
- For press releases: one summary, followed by list of publications
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class MorningBrief:
    """Generates concise morning brief from the 1st cut articles."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.state_file = output_dir / "last_run_articles.json"

    def load_first_cut_articles(self) -> dict:
        """Load articles from the 1st cut run (saved by main pipeline)."""
        if not self.state_file.exists():
            logger.warning("No first cut articles found. Run first cut first.")
            return {}

        with open(self.state_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_brief(self, categorized_articles: dict) -> str:
        """
        Generate a concise text brief from categorized articles.
        Format: Category > numbered headlines with publication.
        """
        date_str = datetime.now().strftime("%d %B %Y")
        lines = [f"<b>NSE Morning Brief - {date_str}</b>\n"]

        total = 0
        for category, articles in categorized_articles.items():
            if not articles:
                continue

            lines.append(f"\n<b>▪️ {category}</b>")

            # Group by headline similarity to detect press release duplicates
            seen_headlines = {}
            for article in articles:
                # Simple press release detection: same story, multiple publications
                base_headline = article.get("headline", "")[:50]
                if base_headline in seen_headlines:
                    # Append publication to existing entry
                    seen_headlines[base_headline]["publications"].append(
                        article.get("publication", "")
                    )
                else:
                    seen_headlines[base_headline] = {
                        "headline": article.get("headline", ""),
                        "url": article.get("url", ""),
                        "publication": article.get("publication", ""),
                        "publications": [article.get("publication", "")]
                    }

            idx = 1
            for key, data in seen_headlines.items():
                headline = data["headline"][:80]
                url = data["url"]

                if len(data["publications"]) > 1:
                    # Press release - list all publications
                    pubs = ", ".join(data["publications"])
                    lines.append(
                        f'{idx}. <a href="{url}">{headline}</a>\n'
                        f'   <i>Published in: {pubs}</i>'
                    )
                else:
                    lines.append(
                        f'{idx}. <a href="{url}">{headline}</a> '
                        f'<i>({data["publication"]})</i>'
                    )
                idx += 1
                total += 1

        lines.append(f"\n<i>Total: {total} stories</i>")
        return "\n".join(lines)

    def save_articles_state(self, categorized_articles: dict):
        """
        Save the current articles to state file.
        Used by Final Cut to find delta (new articles since first cut).
        """
        # Convert Article objects to dicts for JSON serialization
        state = {}
        for category, articles in categorized_articles.items():
            state[category] = []
            for article in articles:
                if hasattr(article, 'to_dict'):
                    state[category].append(article.to_dict())
                else:
                    state[category].append(article)

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {sum(len(a) for a in state.values())} articles to state file")
