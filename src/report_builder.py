"""
Report Builder Module
Generates a PDF report with:
- Table of contents (Sr No, Headline, Publication) with clickable links
- Category section dividers
- Article pages with screenshot + headline + clickable link
"""

import logging
from datetime import datetime
from html import escape as html_escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4


class ReportBuilder:
    """Builds the PDF newsletter report."""

    def __init__(self, output_dir: Path, title_prefix: str = "NSE Daily News Update"):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.title_prefix = title_prefix
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Create custom paragraph styles for the report."""
        self.styles.add(ParagraphStyle(
            name="ReportTitle",
            parent=self.styles["Title"],
            fontSize=18,
            spaceAfter=20,
            textColor=colors.HexColor("#003366"),
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name="CategoryHeader",
            parent=self.styles["Heading1"],
            fontSize=14,
            spaceBefore=12,
            spaceAfter=8,
            textColor=colors.HexColor("#003366"),
            borderWidth=1,
            borderColor=colors.HexColor("#003366"),
            borderPadding=5
        ))
        self.styles.add(ParagraphStyle(
            name="ArticleHeadline",
            parent=self.styles["Heading2"],
            fontSize=11,
            spaceBefore=6,
            spaceAfter=4,
            textColor=colors.HexColor("#333333")
        ))
        self.styles.add(ParagraphStyle(
            name="ArticleMeta",
            parent=self.styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#666666"),
            spaceAfter=6
        ))
        self.styles.add(ParagraphStyle(
            name="ArticleLink",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#0066CC"),
            spaceAfter=10
        ))
        self.styles.add(ParagraphStyle(
            name="TOCEntry",
            parent=self.styles["Normal"],
            fontSize=9,
            leading=14
        ))

    def _build_glossary(self, categorized_articles: dict) -> list:
        """Build a glossary/navigation section at the top of the report."""
        elements = []

        glossary_title = Paragraph(
            "<b>Index / Navigation</b>", self.styles["CategoryHeader"]
        )
        elements.append(glossary_title)
        elements.append(Spacer(1, 0.2 * inch))

        # Build category summary with article counts
        for category, articles in categorized_articles.items():
            count = len(articles)
            if count == 0:
                continue
            bullet = Paragraph(
                f'<b>{category}</b> — {count} article{"s" if count != 1 else ""}',
                self.styles["Normal"]
            )
            elements.append(bullet)
            elements.append(Spacer(1, 0.05 * inch))

        elements.append(Spacer(1, 0.3 * inch))
        elements.append(HRFlowable(
            width="100%", thickness=1, color=colors.HexColor("#CCCCCC")
        ))
        elements.append(Spacer(1, 0.3 * inch))
        return elements

    def _build_toc(self, categorized_articles: dict) -> list:
        """Build Table of Contents page with glossary."""
        elements = []
        date_str = datetime.now().strftime("%d %B %Y")
        title = f"{self.title_prefix} - {date_str}"

        elements.append(Paragraph(title, self.styles["ReportTitle"]))
        elements.append(Spacer(1, 0.2 * inch))

        # Glossary / Navigation
        elements.extend(self._build_glossary(categorized_articles))

        # Build TOC table data
        table_data = [["Sr No", "Headline", "Publication"]]
        sr_no = 1

        for category, articles in categorized_articles.items():
            if not articles:
                continue
            # Category header row
            table_data.append([
                "", Paragraph(f"<b>{category}</b>", self.styles["Normal"]), ""
            ])
            for article in articles:
                headline_text = article.headline[:100]
                if len(article.headline) > 100:
                    headline_text += "..."
                # Make headline a clickable link in TOC
                safe_url = html_escape(article.url, quote=True)
                safe_headline = html_escape(headline_text)
                linked_headline = Paragraph(
                    f'<a href="{safe_url}" color="#0066CC"><u>{safe_headline}</u></a>',
                    self.styles["TOCEntry"]
                )
                table_data.append([
                    str(sr_no),
                    linked_headline,
                    article.publication,
                ])
                sr_no += 1

        # Style the TOC table — wider headline, narrower Sr No
        available_width = PAGE_WIDTH - 1.5 * inch
        col_widths = [0.4 * inch, available_width - 0.4 * inch - 1.3 * inch, 1.3 * inch]
        toc_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        toc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003366")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F5F5")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))

        elements.append(toc_table)
        elements.append(PageBreak())
        return elements

    def _build_category_section(self, category: str,
                                articles: list) -> list:
        """Build pages for a single category."""
        elements = []

        if not articles:
            return elements

        # Category divider page
        elements.append(Spacer(1, 2 * inch))
        elements.append(Paragraph(category, self.styles["CategoryHeader"]))
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(PageBreak())

        # Individual article pages
        for article in articles:
            # Escape URL for XML safety (& -> &amp; etc.)
            safe_url = html_escape(article.url, quote=True)
            safe_headline = html_escape(article.headline)

            # Publication name
            elements.append(Paragraph(
                f"<b>{html_escape(article.publication)}</b>",
                self.styles["ArticleMeta"]
            ))

            # Headline with clickable link
            headline_text = (
                f'Headline - <a href="{safe_url}" color="blue">'
                f'<u>{safe_headline}</u></a>'
            )
            elements.append(Paragraph(headline_text, self.styles["ArticleHeadline"]))

            # URL display as clickable link
            url_display = article.url[:100]
            if len(article.url) > 100:
                url_display += "..."
            elements.append(Paragraph(
                f'<a href="{safe_url}" color="blue"><u>{html_escape(url_display)}</u></a>',
                self.styles["ArticleLink"]
            ))

            elements.append(Spacer(1, 0.2 * inch))

            # Screenshot image - maintain original aspect ratio
            if article.screenshot_path and Path(article.screenshot_path).exists():
                try:
                    img = Image(article.screenshot_path)
                    orig_width = img.imageWidth
                    orig_height = img.imageHeight

                    # Available space on page
                    max_width = PAGE_WIDTH - 2 * inch
                    max_height = PAGE_HEIGHT - 3.5 * inch

                    # Scale to fit width, preserving aspect ratio
                    scale = max_width / orig_width
                    new_width = max_width
                    new_height = orig_height * scale

                    # If height exceeds available space, scale down further
                    if new_height > max_height:
                        scale = max_height / orig_height
                        new_height = max_height
                        new_width = orig_width * scale

                    img = Image(
                        article.screenshot_path,
                        width=new_width,
                        height=new_height
                    )
                    img.hAlign = "CENTER"
                    elements.append(img)
                except Exception as e:
                    logger.warning(
                        f"Failed to embed screenshot for {article.headline}: {e}"
                    )
                    elements.append(Paragraph(
                        "<i>[Screenshot unavailable]</i>",
                        self.styles["Normal"]
                    ))
            else:
                elements.append(Paragraph(
                    "<i>[Screenshot unavailable]</i>",
                    self.styles["Normal"]
                ))

            elements.append(PageBreak())

        return elements

    def build_report(self, categorized_articles: dict) -> Path:
        """
        Build the full PDF report.
        Returns the path to the generated PDF file.
        """
        date_str = datetime.now().strftime("%d%b%Y").replace(" ", "")
        filename = f"NSE_Daily_News_Update_{date_str}.pdf"
        output_path = self.output_dir / filename

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch
        )

        elements = []

        # Table of Contents
        elements.extend(self._build_toc(categorized_articles))

        # Category sections with articles
        for category, articles in categorized_articles.items():
            elements.extend(self._build_category_section(category, articles))

        # Build PDF
        try:
            doc.build(elements)
            logger.info(f"PDF report generated: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to build PDF report: {e}")
            raise
