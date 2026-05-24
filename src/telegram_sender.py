"""
Telegram Sender Module
Sends the newsletter via Telegram:
- Inline summary message (categorized headlines + links)
- PDF attachment
"""

import logging
import urllib3
from pathlib import Path

import requests

# Suppress SSL warnings for corporate proxy environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramSender:
    """Sends newsletter reports via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str,
                 max_message_length: int = 4096):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.max_message_length = max_message_length
        self.api_base = TELEGRAM_API_BASE.format(token=bot_token)

    def _send_message(self, text: str, parse_mode: str = "HTML",
                      disable_preview: bool = True) -> bool:
        """Send a text message via Telegram."""
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview
        }

        try:
            response = requests.post(url, json=payload, timeout=30, verify=False)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
        except requests.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def _send_document(self, file_path: Path, caption: str = "") -> bool:
        """Send a document (PDF) via Telegram."""
        url = f"{self.api_base}/sendDocument"

        try:
            with open(file_path, "rb") as f:
                files = {"document": (file_path.name, f, "application/pdf")}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption[:1024] if caption else "",
                    "parse_mode": "HTML"
                }
                response = requests.post(
                    url, data=data, files=files, timeout=120, verify=False
                )
                response.raise_for_status()
                result = response.json()
                if result.get("ok"):
                    logger.info(f"PDF sent via Telegram: {file_path.name}")
                    return True
                else:
                    logger.error(f"Telegram API error: {result}")
                    return False
        except requests.RequestException as e:
            logger.error(f"Failed to send PDF via Telegram: {e}")
            return False

    def _build_inline_summary(self, categorized_articles: dict,
                              report_date: str) -> list[str]:
        """
        Build inline summary messages.
        Returns list of messages (split if too long for Telegram).
        """
        messages = []
        current_msg = f"<b>📰 NSE Daily News Update - {report_date}</b>\n\n"

        for category, articles in categorized_articles.items():
            if not articles:
                continue

            section = f"<b>▪️ {category}</b>\n"
            for i, article in enumerate(articles, 1):
                headline = article.headline[:70]
                if len(article.headline) > 70:
                    headline += "..."
                pub_info = article.publication
                # Show other publications that carried the same story
                also_in = getattr(article, 'also_published_in', [])
                if also_in:
                    pub_info += f", {', '.join(also_in[:3])}"
                    if len(also_in) > 3:
                        pub_info += f" +{len(also_in)-3} more"
                line = (
                    f'{i}. <a href="{article.url}">{headline}</a> '
                    f'<i>({pub_info})</i>\n'
                )
                section += line

            section += "\n"

            # Check if adding this section exceeds limit
            if len(current_msg) + len(section) > self.max_message_length:
                messages.append(current_msg)
                current_msg = section
            else:
                current_msg += section

        if current_msg.strip():
            messages.append(current_msg)

        return messages

    def send_newsletter(self, categorized_articles: dict,
                        pdf_path: Path, report_date: str) -> bool:
        """
        Send the complete newsletter via Telegram:
        1. Inline summary message(s) with headlines + links
        2. PDF attachment

        Returns True if all messages sent successfully.
        """
        success = True

        # 1. Send inline summary
        summary_messages = self._build_inline_summary(
            categorized_articles, report_date
        )

        for i, msg in enumerate(summary_messages):
            if not self._send_message(msg):
                logger.error(f"Failed to send summary message {i+1}")
                success = False

        # 2. Send PDF attachment
        if pdf_path and pdf_path.exists():
            caption = f"<b>NSE Daily News Update - {report_date}</b>\nFull report attached."
            if not self._send_document(pdf_path, caption):
                logger.error("Failed to send PDF attachment")
                success = False
        else:
            logger.warning(f"PDF not found at {pdf_path}, skipping attachment")
            success = False

        return success

    def send_error_notification(self, error_message: str) -> bool:
        """Send an error notification to the Telegram chat."""
        text = (
            f"<b>⚠️ Newsletter Generation Error</b>\n\n"
            f"<code>{error_message[:3000]}</code>"
        )
        return self._send_message(text)
