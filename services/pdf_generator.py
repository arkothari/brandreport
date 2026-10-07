"""ReportLab PDF generator for brand evaluation reports."""

import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config import settings
from services.brand_researcher import SECTIONS

# ── Colors ────────────────────────────────────────────────────────────────────

PRIMARY   = HexColor("#2563EB")
DARK_BG   = HexColor("#1E3A5F")
LIGHT_BG  = HexColor("#EFF6FF")
TEXT      = HexColor("#1F2937")
MUTED     = HexColor("#6B7280")
WHITE     = HexColor("#FFFFFF")
DIVIDER   = HexColor("#E5E7EB")
ACCENT    = HexColor("#DBEAFE")

# Display order in PDF (exec summary first, then rest in order)
PDF_SECTION_ORDER = ["executive_summary"] + [
    s["key"] for s in SECTIONS if s["key"] not in ("executive_summary",)
]


# ── Styles ────────────────────────────────────────────────────────────────────

def _make_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=WHITE,
            leading=36,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            fontName="Helvetica",
            fontSize=14,
            textColor=HexColor("#BFDBFE"),
            leading=20,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName="Helvetica",
            fontSize=10,
            textColor=HexColor("#93C5FD"),
            leading=16,
        ),
        "section_header": ParagraphStyle(
            "SectionHeader",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=WHITE,
            leading=20,
            leftIndent=6,
        ),
        "h2": ParagraphStyle(
            "H2",
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=PRIMARY,
            leading=18,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "h3": ParagraphStyle(
            "H3",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=TEXT,
            leading=16,
            spaceBefore=8,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=9.5,
            textColor=TEXT,
            leading=15,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            fontName="Helvetica",
            fontSize=9.5,
            textColor=TEXT,
            leading=15,
            leftIndent=16,
            spaceAfter=3,
        ),
        "source": ParagraphStyle(
            "Source",
            fontName="Helvetica",
            fontSize=8.5,
            textColor=MUTED,
            leading=13,
            spaceAfter=2,
        ),
        "footer": ParagraphStyle(
            "Footer",
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            leading=12,
        ),
    }


# ── Markdown → ReportLab elements ─────────────────────────────────────────────

def _md_inline(text: str) -> str:
    """Convert inline markdown (bold, italic, links) to ReportLab XML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Links: [text](url) → text (url)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)
    # Escape remaining ampersands (ReportLab XML quirk)
    text = text.replace("&", "&amp;")
    return text


def md_to_elements(content: str, styles: dict) -> list:
    """Parse markdown text into a list of ReportLab flowables."""
    elements = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # ## H2
        if stripped.startswith("## "):
            text = _md_inline(stripped[3:])
            elements.append(Paragraph(text, styles["h2"]))

        # ### H3
        elif stripped.startswith("### "):
            text = _md_inline(stripped[4:])
            elements.append(Paragraph(text, styles["h3"]))

        # # H1 (treat as H2 in body)
        elif stripped.startswith("# "):
            text = _md_inline(stripped[2:])
            elements.append(Paragraph(text, styles["h2"]))

        # Bullet: - or *
        elif stripped.startswith("- ") or stripped.startswith("* "):
            text = _md_inline(stripped[2:])
            elements.append(Paragraph(f"• {text}", styles["bullet"]))

        # Numbered list: 1. ...
        elif re.match(r"^\d+\.\s", stripped):
            text = _md_inline(re.sub(r"^\d+\.\s", "", stripped))
            elements.append(Paragraph(f"• {text}", styles["bullet"]))

        # Bold line as sub-header (standalone **...**)
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            text = _md_inline(stripped)
            elements.append(Paragraph(text, styles["h3"]))

        # Horizontal rule
        elif stripped in ("---", "***", "___"):
            elements.append(HRFlowable(width="100%", thickness=0.5, color=DIVIDER, spaceAfter=4))

        # Regular paragraph
        else:
            text = _md_inline(stripped)
            if text:
                elements.append(Paragraph(text, styles["body"]))

        i += 1

    return elements


# ── Page template (header/footer) ─────────────────────────────────────────────

class _PageTemplate:
    def __init__(self, brand: str, report_date: str):
        self.brand = brand
        self.report_date = report_date

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = A4
        margin = 1.5 * cm

        # Footer line
        canvas.setStrokeColor(DIVIDER)
        canvas.setLineWidth(0.5)
        canvas.line(margin, margin, w - margin, margin)

        # Footer text
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, margin - 0.4 * cm, f"Brand Evaluation Report · {self.brand} · {self.report_date}")
        canvas.drawRightString(w - margin, margin - 0.4 * cm, f"Page {doc.page}")

        canvas.restoreState()


# ── Cover page ────────────────────────────────────────────────────────────────

def _cover_page(brand: str, industry: str, market: str, report_date: str, styles: dict) -> list:
    w, h = A4
    elements = []

    # Dark header block (drawn as a table cell)
    header_data = [[
        Paragraph(f"Brand Evaluation Report", styles["subtitle"]),
    ]]
    header_table = Table(header_data, colWidths=[w - 3 * cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 40),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)

    # Brand name block
    brand_data = [[Paragraph(brand, styles["title"])]]
    brand_table = Table(brand_data, colWidths=[w - 3 * cm])
    brand_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 24),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
    ]))
    elements.append(brand_table)

    elements.append(Spacer(1, 1.5 * cm))

    # Meta info table
    meta = [
        ["Industry / Category:", industry],
        ["Market / Region:", market],
        ["Report Date:", report_date],
    ]
    meta_table = Table(meta, colWidths=[5 * cm, 10 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, DIVIDER),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 1 * cm))
    elements.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceAfter=12))
    elements.append(Spacer(1, 0.5 * cm))

    elements.append(
        Paragraph(
            "This report was generated by GEO Brand Evaluator using AI-assisted research "
            "combining Claude (Anthropic), OpenAI, and live web data via Tavily Search. "
            "All findings are based on publicly available information.",
            styles["body"],
        )
    )

    elements.append(PageBreak())
    return elements


# ── Section block ─────────────────────────────────────────────────────────────

def _section_block(label: str, content: str, styles: dict, is_sources: bool = False) -> list:
    elements = []

    # Section header bar
    header_data = [[Paragraph(label, styles["section_header"])]]
    header_table = Table(header_data, colWidths=[A4[0] - 3 * cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PRIMARY if not is_sources else DARK_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.3 * cm))

    if is_sources:
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("**") and line.endswith("**"):
                elements.append(Paragraph(_md_inline(line), styles["h3"]))
            elif line.startswith("- ["):
                # [title](url) format
                m = re.match(r"- \[(.+?)\]\((.+?)\)", line)
                if m:
                    elements.append(Paragraph(f"• {m.group(1)} — {m.group(2)}", styles["source"]))
                else:
                    elements.append(Paragraph(line[2:], styles["source"]))
            elif line.startswith("-"):
                elements.append(Paragraph(line[2:], styles["source"]))
            else:
                elements.append(Paragraph(_md_inline(line), styles["body"]))
    else:
        elements.extend(md_to_elements(content, styles))

    elements.append(Spacer(1, 0.6 * cm))
    return elements


# ── PDF generation ────────────────────────────────────────────────────────────

def _build_pdf(path: str, brand: str, industry: str, market: str,
               sections: dict, exec_content: str, all_sources: list):
    report_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    styles = _make_styles()
    page_tmpl = _PageTemplate(brand, report_date)

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
        title=f"Brand Evaluation Report — {brand}",
        author="GEO Brand Evaluator",
        subject=f"{brand} brand analysis",
    )

    story = []

    # Cover
    story.extend(_cover_page(brand, industry, market, report_date, styles))

    # Executive summary (first section)
    story.extend(_section_block("Executive Summary", exec_content, styles))

    # Remaining sections in display order
    display_order = [s for s in PDF_SECTION_ORDER if s != "executive_summary"]
    for key in display_order:
        sec = sections.get(key)
        if not sec:
            continue
        label = sec.get("label", key)
        content = sec.get("content", "")
        if not content:
            continue
        is_sources = key == "sources"
        story.extend(_section_block(label, content, styles, is_sources=is_sources))

    doc.build(story, onFirstPage=page_tmpl, onLaterPages=page_tmpl)


async def generate_pdf(
    report_id: str,
    brand: str,
    industry: str,
    market: str,
    completed_sections: dict,
    exec_content: str,
    all_sources: list,
) -> str:
    pdf_dir = Path(settings.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    path = str(pdf_dir / f"{report_id}.pdf")

    # Build a sections dict mapping key → {label, content} for the PDF builder
    from services.brand_researcher import SECTIONS as SECTION_DEFS
    sections_for_pdf: dict = {}
    for s in SECTION_DEFS:
        key = s["key"]
        if key == "executive_summary":
            sections_for_pdf[key] = {"label": s["label"], "content": exec_content}
        elif key in completed_sections:
            sections_for_pdf[key] = {"label": s["label"], "content": completed_sections[key]}

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _build_pdf(path, brand, industry, market, sections_for_pdf, exec_content, all_sources),
    )
    return path
