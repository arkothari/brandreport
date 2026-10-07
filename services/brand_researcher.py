"""Brand research orchestrator: Tavily web search + Claude analysis, one section at a time."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import anthropic
from openai import AsyncOpenAI
from tavily import TavilyClient

from config import settings
from database import save_section, save_sources, save_pdf_path, update_report_status

logger = logging.getLogger(__name__)

# ── Section registry ────────────────────────────────────────────────────────

SECTIONS = [
    {"key": "brand_overview",  "label": "Brand Overview"},
    {"key": "market_context",  "label": "Market & Category Context"},
    {"key": "positioning",     "label": "Brand Positioning"},
    {"key": "competitors",     "label": "Competitors"},
    {"key": "customer_voice",  "label": "Customer Voice"},
    {"key": "audience",        "label": "Audience Perception"},
    {"key": "seo_geo",         "label": "Visibility"},
    {"key": "public_market",   "label": "Public Market Performance"},
    {"key": "swot",            "label": "SWOT Analysis"},
    {"key": "recommendations", "label": "Recommendations"},
    {"key": "sources",         "label": "Sources & Citations"},
    {"key": "executive_summary", "label": "Executive Summary"},
]

SECTION_KEYS = [s["key"] for s in SECTIONS]

# ── SSE subscriber registry ─────────────────────────────────────────────────

_subscribers: dict[str, set[asyncio.Queue]] = {}


def subscribe(report_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(report_id, set()).add(q)
    return q


def unsubscribe(report_id: str, q: asyncio.Queue):
    _subscribers.get(report_id, set()).discard(q)


async def broadcast(report_id: str, event_type: str, data: dict):
    for q in list(_subscribers.get(report_id, set())):
        await q.put({"type": event_type, "data": data})


# ── Tavily search ────────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
    if not settings.tavily_api_key:
        return []
    try:
        client = TavilyClient(api_key=settings.tavily_api_key)
        kwargs = {"query": query, "max_results": max_results, "search_depth": "advanced"}
        if days:
            kwargs["days"] = days
        result = client.search(**kwargs)
        return result.get("results", [])
    except Exception as e:
        logger.warning("Tavily search error for '%s': %s", query, e)
        return []


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _tavily_search(query, max_results))


async def web_search_recent(query: str, max_results: int = 5, days: int = 180) -> list[dict]:
    """Search with a recency filter — use for fast-moving data (financials, reviews, news)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _tavily_search(query, max_results, days))


def fmt_results(results: list[dict]) -> str:
    if not results:
        return "No search results available."
    parts = []
    for i, r in enumerate(results, 1):
        content = (r.get("content") or r.get("raw_content") or "")[:600]
        parts.append(
            f"[{i}] {r.get('title', 'N/A')}\n"
            f"URL: {r.get('url', '')}\n"
            f"Excerpt: {content}"
        )
    return "\n\n".join(parts)


def collect_sources(results: list[dict], section_label: str) -> list[dict]:
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "section": section_label}
        for r in results
        if r.get("url")
    ]


# ── Claude client ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an expert brand strategist and market analyst. "
    "You write clear, professional, evidence-based brand evaluation reports. "
    "When you write a section, use markdown: ## for section headers, ### for sub-headers, "
    "**bold** for key terms, and bullet lists where they improve clarity. "
    "Be specific and data-driven. Avoid generic marketing language."
)


async def ask_claude(prompt: str, max_tokens: int = 4000) -> str:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text_block = next((b for b in response.content if getattr(b, "type", "") == "text"), None)
    if not text_block:
        logger.warning("No text block in response; types: %s", [getattr(b, "type", "?") for b in response.content])
        return ""
    return text_block.text


async def ask_openai(prompt: str, max_tokens: int = 600) -> str:
    if not settings.openai_api_key:
        return ""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


# ── Research context helper ──────────────────────────────────────────────────

def _current_year() -> int:
    return datetime.now().year


def _current_date_str() -> str:
    return datetime.now().strftime("%B %Y")


def brand_header(ctx: dict) -> str:
    competitors_note = ""
    if ctx.get("competitors"):
        competitors_note = f"\nKnown competitors: {', '.join(ctx['competitors'])}"
    return (
        f"Brand: **{ctx['brand']}**\n"
        f"Industry: {ctx['industry']}\n"
        f"Market/Region: {ctx['market']}\n"
        f"Report date: {_current_date_str()} — use only current, up-to-date information"
        + competitors_note
    )


def prior_sections_summary(ctx: dict) -> str:
    done = ctx.get("completed_sections", {})
    if not done:
        return ""
    parts = []
    for key, content in done.items():
        label = next((s["label"] for s in SECTIONS if s["key"] == key), key)
        # Include only first 500 chars to keep prompt size manageable
        parts.append(f"### {label}\n{content[:500]}...")
    return "\n\n".join(parts)


# ── Section research functions ───────────────────────────────────────────────

async def research_brand_overview(ctx: dict, all_sources: list) -> str:
    brand, industry, market = ctx["brand"], ctx["industry"], ctx["market"]
    r1 = await web_search(f"{brand} company overview history founded")
    r2 = await web_search(f"{brand} {industry} products services business model")
    sources = collect_sources(r1 + r2, "Brand Overview")
    all_sources.extend(sources)
    prompt = f"""
{brand_header(ctx)}

Write the **Brand Overview** section for a professional brand evaluation report.

Cover:
- Founding story, headquarters, leadership
- Core business model and revenue streams
- Key products / services
- Geographic footprint and scale (employees, revenue if known)
- Recent milestones or pivots

Target: 200–250 words. Use markdown formatting.

RESEARCH FINDINGS:
{fmt_results(r1 + r2)}
"""
    return await ask_claude(prompt)


async def research_market_context(ctx: dict, all_sources: list) -> str:
    brand, industry, market = ctx["brand"], ctx["industry"], ctx["market"]
    r1 = await web_search_recent(f"{industry} market size growth trends {_current_year()}", days=365)
    r2 = await web_search_recent(f"{market} {industry} market landscape competitive dynamics {_current_year()}", days=365)
    sources = collect_sources(r1 + r2, "Market & Category Context")
    all_sources.extend(sources)
    prompt = f"""
{brand_header(ctx)}

Write the **Market & Category Context** section.

Cover:
- Market size and growth rate
- Key market drivers and headwinds
- Macro trends shaping the category
- Regulatory or technology forces at play
- Where {brand} sits in this landscape

Target: 200–250 words. Use markdown formatting.

RESEARCH FINDINGS:
{fmt_results(r1 + r2)}
"""
    return await ask_claude(prompt)


async def research_positioning(ctx: dict, all_sources: list) -> str:
    brand, industry, market = ctx["brand"], ctx["industry"], ctx["market"]
    r1 = await web_search(f"{brand} brand positioning value proposition messaging")
    r2 = await web_search(f"{brand} target market customer segment strategy")
    sources = collect_sources(r1 + r2, "Brand Positioning")
    all_sources.extend(sources)
    prior = prior_sections_summary(ctx)
    prompt = f"""
{brand_header(ctx)}

Write the **Brand Positioning** section.

Cover:
- How {brand} positions itself in the market
- Unique value proposition (UVP)
- Target customer segments
- Pricing tier and quality perception
- Brand personality / tone

Target: 200–250 words. Use markdown formatting.

RESEARCH FINDINGS:
{fmt_results(r1 + r2)}

PRIOR SECTIONS (for context):
{prior or 'N/A'}
"""
    return await ask_claude(prompt)


async def research_competitors(ctx: dict, all_sources: list) -> str:
    brand, industry, market = ctx["brand"], ctx["industry"], ctx["market"]
    competitors_hint = ""
    if ctx.get("competitors"):
        competitors_hint = f"User-identified competitors: {', '.join(ctx['competitors'])}."
    r1 = await web_search_recent(f"{brand} competitors alternatives comparison {industry} {_current_year()}", days=365)
    r2 = await web_search_recent(f"top {industry} companies {market} market leaders {_current_year()}", days=365)
    sources = collect_sources(r1 + r2, "Competitors")
    all_sources.extend(sources)
    prompt = f"""
{brand_header(ctx)}
{competitors_hint}

Write the **Competitors** section.

Identify 5–7 direct competitors for {brand}. For each competitor provide:
- Name and brief description
- Key differentiator vs. {brand}
- Estimated market standing (leader / challenger / niche)

End with a short paragraph on the competitive intensity overall.

Target: 250–300 words. Use a structured list format.

RESEARCH FINDINGS:
{fmt_results(r1 + r2)}
"""
    return await ask_claude(prompt)


async def research_swot(ctx: dict, all_sources: list) -> str:
    brand, industry = ctx["brand"], ctx["industry"]
    r1 = await web_search_recent(f"{brand} strengths competitive advantages {_current_year()}")
    r2 = await web_search_recent(f"{brand} weaknesses problems criticism {_current_year()}")
    r3 = await web_search_recent(f"{brand} growth opportunities market expansion {_current_year()}")
    r4 = await web_search_recent(f"{brand} threats competitive risks challenges {industry} {_current_year()}")
    sources = collect_sources(r1 + r2 + r3 + r4, "SWOT Analysis")
    all_sources.extend(sources)
    prior = prior_sections_summary(ctx)
    prompt = f"""
{brand_header(ctx)}

Write a comprehensive SWOT Analysis for {brand}. Structure it with exactly these four headers:

## Strengths
List 4–5 evidence-based strengths with a brief explanation for each.

## Weaknesses
List 3–4 notable weaknesses or areas for improvement, backed by evidence. Be candid.

## Opportunities
List 3–4 concrete growth opportunities: underserved segments, new markets, tech trends, partnerships.

## Threats
List 3–4 key threats: competitive pressure, regulatory risks, market headwinds, disruptive forces.

Each quadrant: 100–130 words. Total target: 450–500 words. Use bullet points within each section.

RESEARCH FINDINGS:
{fmt_results(r1 + r2 + r3 + r4)}

PRIOR SECTIONS (for context):
{prior or 'N/A'}
"""
    return await ask_claude(prompt, max_tokens=5000)


_INDUSTRY_ETF = {
    "technology": "XLK", "tech": "XLK", "software": "XLK", "saas": "XLK", "cloud": "XLK",
    "semiconductor": "SOXX", "chip": "SOXX",
    "retail": "XRT", "e-commerce": "IBUY", "ecommerce": "IBUY",
    "consumer": "XLY", "apparel": "XLY", "fashion": "XLY",
    "travel": "AWAY", "hospitality": "AWAY", "hotel": "AWAY",
    "airlines": "JETS", "aviation": "JETS", "aerospace": "ITA",
    "healthcare": "XLV", "pharma": "XPH", "pharmaceutical": "XPH",
    "biotech": "XBI", "biotechnology": "XBI",
    "financial": "XLF", "finance": "XLF", "banking": "KBE",
    "energy": "XLE", "oil": "XLE", "renewable": "ICLN",
    "automotive": "CARZ",
    "media": "XLC", "communication": "XLC", "streaming": "XLC",
    "food": "XLP", "beverage": "XLP",
    "utilities": "XLU", "real estate": "XLRE",
    "industrial": "XLI", "manufacturing": "XLI",
}


def _industry_etf(industry: str) -> str:
    low = industry.lower()
    for kw, etf in _INDUSTRY_ETF.items():
        if kw in low:
            return etf
    return "SPY"


async def research_public_market(ctx: dict, all_sources: list) -> str:
    brand, industry = ctx["brand"], ctx["industry"]
    r1 = await web_search_recent(f"{brand} stock NYSE NASDAQ market cap {_current_year()}", days=90)
    r2 = await web_search_recent(f"{brand} earnings revenue financial results {_current_year()}", days=90)
    r3 = await web_search_recent(f"{brand} analyst rating price target {_current_year()}", days=90)
    sources = collect_sources(r1 + r2 + r3, "Public Market Performance")
    all_sources.extend(sources)

    # Ask Claude to identify the ticker (very short, targeted call)
    ticker_resp = await ask_claude(
        f"What is the primary stock ticker for {brand} on NYSE, NASDAQ, or another major exchange? "
        f"Reply with ONLY the ticker symbol (e.g., AAPL) or 'PRIVATE' if it is not publicly traded. No other text.",
        max_tokens=15,
    )
    ticker = ticker_resp.strip().upper().split()[0] if ticker_resp.strip() else "PRIVATE"
    if len(ticker) > 6 or not ticker.isalpha():
        ticker = "PRIVATE"
    etf = _industry_etf(industry)

    prompt = f"""
{brand_header(ctx)}

Write a concise **Public Market Performance** section for {brand} in 100–130 words.

{"This brand trades under ticker **" + ticker + "**." if ticker != "PRIVATE" else ""}

If {brand} is publicly traded, include in 2–3 short sentences each:
- Stock ticker, exchange, approximate market cap, and 12-month price trend
- One key financial metric (revenue growth or profitability)
- Analyst consensus and general investor sentiment

If {brand} is private, note that briefly and mention last known valuation or funding round in 2–3 sentences.

No headers. Plain prose. No bullet points.

RESEARCH FINDINGS:
{fmt_results(r1 + r2 + r3)}
"""
    content = await ask_claude(prompt, max_tokens=500)

    # Embed ticker metadata for the frontend chart
    if ticker != "PRIVATE":
        content = f"<!-- STOCK:{ticker}|COMPARE:{etf} -->\n" + content

    return content


async def research_customer_voice(ctx: dict, all_sources: list) -> str:
    brand = ctx["brand"]
    r1 = await web_search_recent(f"{brand} trustpilot g2 capterra rating score reviews {_current_year()}", days=180)
    r2 = await web_search_recent(f"{brand} glassdoor app store reviews customer satisfaction {_current_year()}", days=180)
    r3 = await web_search_recent(f"{brand} reddit customer opinions sentiment {_current_year()}", days=180)
    r4 = await web_search_recent(f"{brand} social media sentiment complaints praise {_current_year()}", days=90)
    sources = collect_sources(r1 + r2 + r3 + r4, "Customer Voice")
    all_sources.extend(sources)
    prompt = f"""
{brand_header(ctx)}

Write the **Customer Voice** section for {brand}. This is a unified view of customer sentiment and ratings.

Structure it with these two sub-sections:

**1. Platform Ratings**
Summarize scores across major review platforms (include specific scores if available):
- Trustpilot, G2, Capterra (if applicable)
- Glassdoor (employer brand perspective)
- App Store / Google Play (if applicable)
- Note what drives high vs. low ratings on each platform.

**2. Sentiment & Themes**
- Overall sentiment polarity: Positive / Mixed / Negative — and the primary reason
- Top 3 praise themes (what customers love most)
- Top 3 complaint themes (recurring pain points)
- Any notable shifts in sentiment over time or differences between user segments

Target: 300–350 words total. Be specific and evidence-based.

RESEARCH FINDINGS:
{fmt_results(r1 + r2 + r3 + r4)}
"""
    return await ask_claude(prompt, max_tokens=4000)


async def research_seo_geo(ctx: dict, all_sources: list) -> str:
    brand, industry, market = ctx["brand"], ctx["industry"], ctx["market"]
    r1 = await web_search_recent(f"{brand} {industry} search visibility online presence {_current_year()}", days=180)
    r2 = await web_search_recent(f"site:reddit.com {brand}", days=180)
    sources = collect_sources(r1 + r2, "Visibility")
    all_sources.extend(sources)

    # GEO: Ask Claude about the brand (self-assessment)
    claude_geo = ""
    try:
        claude_geo = await ask_claude(
            f"In 2-3 sentences, describe what you know about {brand} as a company in the {industry} space. "
            f"Be objective and factual.",
            max_tokens=200,
        )
    except Exception:
        claude_geo = "Unable to retrieve Claude's assessment."

    # GEO: Ask OpenAI about the brand
    openai_geo = ""
    try:
        openai_geo = await ask_openai(
            f"In 2-3 sentences, describe what you know about {brand} as a company in the {industry} space. "
            f"Be objective and factual.",
            max_tokens=200,
        )
    except Exception:
        openai_geo = "OpenAI API not configured or unavailable."

    prompt = f"""
{brand_header(ctx)}

Write the **Visibility** section for {brand}.

This section covers two areas:

**1. SEO Visibility** — How {brand} appears in traditional web search:
- Online presence strength (official site, social media, news coverage)
- Search result prominence for key category queries
- Presence on review sites, forums (Reddit, etc.)

**2. GEO Visibility (Generative Engine Optimization)** — How AI assistants describe {brand}:
- Claude (Anthropic) says: "{claude_geo}"
- ChatGPT (OpenAI) says: "{openai_geo}"
- Analyze: Is the brand well-represented in AI responses? What attributes do AI models emphasize? Any gaps or inaccuracies?

Target: 250–300 words. Use the two sub-sections above.

WEB SEARCH FINDINGS:
{fmt_results(r1 + r2)}
"""
    return await ask_claude(prompt, max_tokens=4000)


async def research_audience(ctx: dict, all_sources: list) -> str:
    brand, industry = ctx["brand"], ctx["industry"]
    r1 = await web_search_recent(f"{brand} target audience customer demographics profile {_current_year()}", days=365)
    r2 = await web_search_recent(f"{brand} who uses customer type buyer persona {_current_year()}", days=365)
    sources = collect_sources(r1 + r2, "Audience Perception")
    all_sources.extend(sources)
    prior = prior_sections_summary(ctx)
    prompt = f"""
{brand_header(ctx)}

Write the **Audience Perception** section for {brand}.

Cover:
- Primary customer segments (B2B vs. B2C, demographics, psychographics)
- How different audience groups perceive the brand
- Brand loyalty and advocacy levels
- Any perception gaps (what the brand says vs. what customers believe)

Target: 200–250 words.

RESEARCH FINDINGS:
{fmt_results(r1 + r2)}

PRIOR SECTIONS (for context):
{prior or 'N/A'}
"""
    return await ask_claude(prompt)




async def research_recommendations(ctx: dict, all_sources: list) -> str:
    prior = prior_sections_summary(ctx)
    prompt = f"""
{brand_header(ctx)}

Write the **Recommendations** section based on the full brand evaluation below.

Provide 5–7 prioritized, actionable recommendations. Use EXACTLY this format for each recommendation:

### [Recommendation title]
[1–2 sentence rationale tied to specific findings]
**Priority:** High | Medium | Low  **Timeline:** Quick win (<3 mo) | Medium term (3–12 mo) | Long term (12+ mo)

Recommendations must span: brand strategy, product/service, marketing, competitive positioning, and risk mitigation.

FULL ANALYSIS SUMMARY:
{prior or 'No prior sections available.'}
"""
    return await ask_claude(prompt, max_tokens=5000)


def compile_sources_section(all_sources: list) -> str:
    seen_urls: set = set()
    unique = []
    for s in all_sources:
        url = s.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(s)

    if not unique:
        return "No external sources were retrieved during this evaluation."

    # Group by section
    by_section: dict[str, list] = {}
    for s in unique:
        section = s.get("section", "General")
        by_section.setdefault(section, []).append(s)

    lines = ["The following sources were consulted during this brand evaluation:\n"]
    for section, sources in by_section.items():
        lines.append(f"\n**{section}**")
        for s in sources:
            title = s.get("title") or s["url"]
            url = s["url"]
            lines.append(f"- [{title}]({url})")
    return "\n".join(lines)


async def research_executive_summary(ctx: dict, all_sources: list) -> str:
    prior = prior_sections_summary(ctx)
    prompt = f"""
{brand_header(ctx)}

Write the **Executive Summary** for this brand evaluation report.

This appears first in the report and must capture the essential story in 200–250 words:
- What {ctx['brand']} is and does (1 sentence)
- Overall brand health assessment (strong / moderate / at risk) and why
- 3 top strengths
- 3 key challenges or weaknesses
- Most important opportunity
- Single most critical recommendation

Write in a compelling, executive-ready tone. This section is what a busy decision-maker reads first.

FULL ANALYSIS:
{prior or 'No prior sections available.'}
"""
    return await ask_claude(prompt, max_tokens=4000)


# ── Section dispatch ──────────────────────────────────────────────────────────

_SECTION_HANDLERS = {
    "brand_overview":   research_brand_overview,
    "market_context":   research_market_context,
    "positioning":      research_positioning,
    "competitors":      research_competitors,
    "swot":             research_swot,
    "customer_voice":   research_customer_voice,
    "public_market":    research_public_market,
    "seo_geo":          research_seo_geo,
    "audience":         research_audience,
    "recommendations":  research_recommendations,
}


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run_evaluation(
    report_id: str,
    brand: str,
    industry: str,
    market: str,
    competitors: list[str],
):
    from services.pdf_generator import generate_pdf

    await update_report_status(report_id, "running")
    await broadcast(report_id, "status", {"status": "running"})

    ctx: dict = {
        "brand": brand,
        "industry": industry,
        "market": market,
        "competitors": competitors,
        "completed_sections": {},
    }
    all_sources: list = []

    # Research sections sequentially (exec summary and sources are last)
    research_order = [s["key"] for s in SECTIONS if s["key"] not in ("sources", "executive_summary")]

    for section_key in research_order:
        label = next(s["label"] for s in SECTIONS if s["key"] == section_key)
        await broadcast(report_id, "section_start", {"section": section_key, "label": label})

        try:
            handler = _SECTION_HANDLERS[section_key]
            content = await handler(ctx, all_sources)
            ctx["completed_sections"][section_key] = content

            section_data = {"label": label, "status": "complete", "content": content}
            await save_section(report_id, section_key, section_data)
            await broadcast(report_id, "section_complete", {
                "section": section_key,
                "label": label,
                "content": content,
            })

        except Exception as e:
            logger.exception("Section %s failed for report %s", section_key, report_id)
            error_content = f"*This section could not be generated: {e}*"
            section_data = {"label": label, "status": "error", "content": error_content}
            await save_section(report_id, section_key, section_data)
            ctx["completed_sections"][section_key] = error_content
            await broadcast(report_id, "section_error", {
                "section": section_key,
                "label": label,
                "error": str(e),
            })

    # Sources
    sources_label = "Sources & Citations"
    await broadcast(report_id, "section_start", {"section": "sources", "label": sources_label})
    sources_content = compile_sources_section(all_sources)
    await save_section(report_id, "sources", {"label": sources_label, "status": "complete", "content": sources_content})
    await save_sources(report_id, all_sources)
    await broadcast(report_id, "section_complete", {
        "section": "sources",
        "label": sources_label,
        "content": sources_content,
    })

    # Executive Summary (last, synthesizes everything)
    exec_label = "Executive Summary"
    await broadcast(report_id, "section_start", {"section": "executive_summary", "label": exec_label})
    try:
        exec_content = await research_executive_summary(ctx, all_sources)
    except Exception as e:
        logger.exception("Executive summary failed for report %s", report_id)
        exec_content = f"*Executive summary could not be generated: {e}*"
    await save_section(report_id, "executive_summary", {"label": exec_label, "status": "complete", "content": exec_content})
    await broadcast(report_id, "section_complete", {
        "section": "executive_summary",
        "label": exec_label,
        "content": exec_content,
    })

    # PDF
    try:
        pdf_path = await generate_pdf(report_id, brand, industry, market, ctx["completed_sections"], exec_content, all_sources)
        await save_pdf_path(report_id, pdf_path)
        await update_report_status(report_id, "completed")
        await broadcast(report_id, "report_complete", {"pdf_available": True})
    except Exception as e:
        logger.exception("PDF generation failed for report %s", report_id)
        await update_report_status(report_id, "completed")
        await broadcast(report_id, "report_complete", {"pdf_available": False, "pdf_error": str(e)})

    # Send sentinel to close all SSE connections
    await broadcast(report_id, "__close__", {})
