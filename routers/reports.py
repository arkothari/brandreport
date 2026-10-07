"""API routes for brand evaluation reports."""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from database import create_report, get_report, list_reports, update_report_status
from services.brand_researcher import (
    SECTIONS,
    broadcast,
    run_evaluation,
    subscribe,
    unsubscribe,
)

router = APIRouter(prefix="/api", tags=["reports"])


# ── Request / Response models ─────────────────────────────────────────────────

class CreateReportRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=200)
    industry: str = Field(..., min_length=1, max_length=200)
    market: str = Field(..., min_length=1, max_length=200)
    competitors: list[str] = Field(default_factory=list)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/reports")
async def get_reports():
    return await list_reports()


@router.post("/reports", status_code=201)
async def create_new_report(request: CreateReportRequest, background_tasks: BackgroundTasks):
    report_id = str(uuid.uuid4())
    competitors = [c.strip() for c in request.competitors if c.strip()]
    report = await create_report(
        report_id,
        request.brand_name,
        request.industry,
        request.market,
        competitors,
    )
    background_tasks.add_task(
        _run_evaluation_safe,
        report_id,
        request.brand_name,
        request.industry,
        request.market,
        competitors,
    )
    return report


async def _run_evaluation_safe(report_id: str, brand: str, industry: str, market: str, competitors: list):
    try:
        await run_evaluation(report_id, brand, industry, market, competitors)
    except Exception as e:
        await update_report_status(report_id, "failed", str(e))
        await broadcast(report_id, "report_error", {"error": str(e)})
        await broadcast(report_id, "__close__", {})


@router.get("/reports/{report_id}")
async def get_report_detail(report_id: str):
    report = await get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/reports/{report_id}/stream")
async def stream_report(report_id: str):
    report = await get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    async def event_generator():
        # Send all already-completed sections from DB first
        report_data = report.get("report_data", {})
        completed = report_data.get("sections", {})
        display_order = ["executive_summary"] + [
            s["key"] for s in SECTIONS if s["key"] != "executive_summary"
        ]
        for key in display_order:
            sec = completed.get(key)
            if sec and sec.get("status") in ("complete", "error"):
                yield _sse("section_complete", {
                    "section": key,
                    "label": sec["label"],
                    "content": sec.get("content", ""),
                })

        # If report is already done, signal and close
        if report["status"] in ("completed", "failed"):
            if report["status"] == "completed":
                yield _sse("report_complete", {"pdf_available": bool(report.get("pdf_path"))})
            else:
                yield _sse("report_error", {"error": report.get("error_message", "Unknown error")})
            return

        # Subscribe to live events
        q = subscribe(report_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if event["type"] == "__close__":
                    break

                yield _sse(event["type"], event["data"])

                if event["type"] in ("report_complete", "report_error"):
                    break
        finally:
            unsubscribe(report_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/reports/{report_id}/pdf")
async def download_pdf(report_id: str):
    report = await get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    pdf_path = report.get("pdf_path")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF not yet available")
    filename = f"{report['brand_name'].replace(' ', '_')}_brand_evaluation.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


@router.get("/sections")
async def get_sections():
    return SECTIONS


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
