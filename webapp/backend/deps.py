"""Shared backend setup: rules, engine, session factory, auth, helpers.

Kept in its own module so routers can import it without circular imports
against ``app.py``.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import Header, HTTPException

from fmlwc.core.config import GameRules
from fmlwc.persistence.db import create_all, make_engine, make_session_factory

RULES = GameRules.from_yaml(ROOT / "config" / "rules.example.yaml")
ENGINE = make_engine(RULES.storage.url)
create_all(ENGINE)
SessionFactory = make_session_factory(ENGINE)

# Dev default; override with FMLWC_ADMIN_TOKEN in production.
ADMIN_TOKEN = os.environ.get("FMLWC_ADMIN_TOKEN", "fmlwc-admin")


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency guarding /api/admin/* and export endpoints that write."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token required (X-Admin-Token header).")


def parse_dt(value: str) -> datetime:
    """Parse an ISO datetime string (naive or with offset) → naive UTC."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Bad datetime: {value!r} (use ISO 8601).")
    return naive(dt.astimezone(timezone.utc)) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# File-building helpers (xlsx / csv / txt streaming)
# ---------------------------------------------------------------------------

def build_xlsx(sheets: dict[str, tuple[list[str], list[list]]]) -> bytes:
    """sheets: {sheet_name: (headers, rows)} → xlsx file bytes."""
    import openpyxl

    wb = openpyxl.Workbook()
    default = wb.active
    first = True
    for name, (headers, rows) in sheets.items():
        ws = default if first else wb.create_sheet()
        ws.title = name[:31]
        first = False
        ws.append(list(headers))
        for row in rows:
            ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_csv(headers: list[str], rows: list[list]) -> bytes:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def file_response(data: bytes, filename: str, media_type: str):
    from fastapi.responses import Response

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
