import json
from datetime import datetime, timezone

import aiosqlite

from config import settings

DB_PATH = settings.db_path


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                brand_name TEXT NOT NULL,
                industry TEXT,
                market TEXT,
                competitors_input TEXT DEFAULT '[]',
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                completed_at TEXT,
                report_data TEXT DEFAULT '{}',
                pdf_path TEXT,
                error_message TEXT
            )
        """)
        await db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_report(
    report_id: str,
    brand_name: str,
    industry: str,
    market: str,
    competitors: list,
) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO reports
               (id, brand_name, industry, market, competitors_input, status, created_at, report_data)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, '{}')""",
            (report_id, brand_name, industry, market, json.dumps(competitors), _now()),
        )
        await db.commit()
    return await get_report(report_id)


async def get_report(report_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["competitors_input"] = json.loads(d.get("competitors_input") or "[]")
        d["report_data"] = json.loads(d.get("report_data") or "{}")
        return d


async def list_reports() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, brand_name, industry, market, status, created_at, completed_at, pdf_path "
            "FROM reports ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_report_status(report_id: str, status: str, error_message: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "completed":
            await db.execute(
                "UPDATE reports SET status = ?, completed_at = ? WHERE id = ?",
                (status, _now(), report_id),
            )
        elif status == "failed" and error_message:
            await db.execute(
                "UPDATE reports SET status = ?, error_message = ? WHERE id = ?",
                (status, error_message, report_id),
            )
        else:
            await db.execute("UPDATE reports SET status = ? WHERE id = ?", (status, report_id))
        await db.commit()


async def save_section(report_id: str, section_key: str, section_data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT report_data FROM reports WHERE id = ?", (report_id,))
        row = await cursor.fetchone()
        if not row:
            return
        data = json.loads(row["report_data"] or "{}")
        data.setdefault("sections", {})[section_key] = section_data
        await db.execute(
            "UPDATE reports SET report_data = ? WHERE id = ?",
            (json.dumps(data), report_id),
        )
        await db.commit()


async def save_sources(report_id: str, sources: list):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT report_data FROM reports WHERE id = ?", (report_id,))
        row = await cursor.fetchone()
        if not row:
            return
        data = json.loads(row["report_data"] or "{}")
        data["sources"] = sources
        await db.execute(
            "UPDATE reports SET report_data = ? WHERE id = ?",
            (json.dumps(data), report_id),
        )
        await db.commit()


async def save_pdf_path(report_id: str, pdf_path: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE reports SET pdf_path = ? WHERE id = ?",
            (pdf_path, report_id),
        )
        await db.commit()
