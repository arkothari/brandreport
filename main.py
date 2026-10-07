import asyncio
import json
import os
import sys
import urllib.request

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from config import settings
from database import init_db
from routers.reports import router as reports_router

app = FastAPI(
    title="GEO Brand Evaluator",
    description="Comprehensive AI-powered brand evaluation reports",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    if not settings.anthropic_api_key:
        print("WARNING: ANTHROPIC_API_KEY not set — required for analysis.", file=sys.stderr)
    if not settings.tavily_api_key:
        print("WARNING: TAVILY_API_KEY not set — web search disabled.", file=sys.stderr)


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/report/{report_id}", include_in_schema=False)
async def report_page(report_id: str):
    return FileResponse("static/report.html")


@app.get("/api/stock-quote")
async def stock_quote(ticker: str = Query(...), compare: str = Query("SPY")):
    def _fetch(symbol: str):
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            "?range=1y&interval=1d&events=history"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def _extract(data):
        try:
            result = data["chart"]["result"][0]
            meta = result["meta"]
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            # first and last non-null close prices give the 1-year return
            valid = [p for p in closes if p is not None]
            change_pct = None
            if len(valid) >= 2:
                change_pct = round((valid[-1] - valid[0]) / valid[0] * 100, 1)
            return {
                "price":      round(meta.get("regularMarketPrice") or meta.get("previousClose") or 0, 2),
                "currency":   meta.get("currency", "USD"),
                "exchange":   meta.get("exchangeName", ""),
                "change_pct": change_pct,  # 1-year % return
            }
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    try:
        raw, cmp_raw = await asyncio.gather(
            loop.run_in_executor(None, lambda: _fetch(ticker)),
            loop.run_in_executor(None, lambda: _fetch(compare)),
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    stock = _extract(raw)
    bench = _extract(cmp_raw)
    if not stock:
        return JSONResponse({"error": "No data for ticker"}, status_code=404)

    return {"ticker": ticker, "stock": stock, "compare": compare, "benchmark": bench}


@app.post("/api/chat/{report_id}")
async def chat(report_id: str, body: dict):
    from database import get_report
    import anthropic as _anthropic
    from fastapi.responses import StreamingResponse as _SR

    report = await get_report(report_id)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    message = (body.get("message") or "").strip()
    history = body.get("history") or []  # list of {role, content}
    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # Build report context from completed sections
    sections = report.get("report_data", {}).get("sections", {})
    ctx_parts = [
        f"## {key.replace('_', ' ').title()}\n{v.get('content', '')}"
        for key, v in sections.items()
        if v.get("content")
    ]
    report_context = "\n\n---\n\n".join(ctx_parts) if ctx_parts else "No report content available."

    brand_name = report.get("brand_name", "this brand")
    industry   = report.get("industry", "")
    market     = report.get("market", "")

    system_prompt = (
        f"You are an expert brand analyst assistant. The user is reading a brand intelligence report "
        f"for **{brand_name}** in the **{industry}** industry, {market} market.\n\n"

        f"SCOPE — only answer questions that are relevant to:\n"
        f"- {brand_name} as a brand (strategy, products, positioning, reputation, financials)\n"
        f"- The {industry} industry and its market dynamics\n"
        f"- Competitors, customer sentiment, market trends, or findings in this report\n"
        f"- Business, marketing, or investment implications of anything in the report\n\n"

        f"OUT OF SCOPE — if a question is unrelated to the brand, industry, or report content "
        f"(e.g. weather, sports, cooking, general trivia, personal advice, or any other topic), "
        f"respond with exactly this format and nothing else:\n"
        f"\"I'm here to help you explore the {brand_name} brand report. "
        f"Try asking about [suggest a relevant topic from the report].\"\n\n"

        f"For in-scope questions: be concise and direct. If something isn't in the report, "
        f"say so briefly and supplement with relevant general knowledge about the brand or industry. "
        f"Use markdown for formatting when helpful.\n\n"
        f"<report>\n{report_context[:12000]}\n</report>"
    )

    messages = [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
    messages.append({"role": "user", "content": message})

    async def _stream():
        client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
        with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text

    return _SR(_stream(), media_type="text/plain")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
        "tavily": bool(settings.tavily_api_key),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
