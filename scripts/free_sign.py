#!/usr/bin/env python3
"""Free-sign interface — trigger from the Python shell or wrap for a web endpoint.

Shell usage
-----------
    python scripts/free_sign.py propose --manager 1 --player 42
    python scripts/free_sign.py propose --manager 1 --player 42 --at "2026-06-04T10:00:00Z"
    python scripts/free_sign.py revoke  --id 7
    python scripts/free_sign.py revoke  --id 7 --at "2026-06-04T10:05:00Z"
    python scripts/free_sign.py commit                   # commit all due signs now
    python scripts/free_sign.py commit --at "2026-06-04T10:20:00Z"

    # Batch propose from a CSV file (see --template for format)
    python scripts/free_sign.py batch signs.csv
    python scripts/free_sign.py batch --template          # print a sample CSV and exit

Programmatic usage (Python shell / web handler)
-----------------------------------------------
    from scripts.free_sign import build_service

    svc = build_service()                              # reads DB + rules from config
    result = svc.try_propose(manager_id=1, player_id=42, posted_at=datetime.now(tz=timezone.utc))
    if result.success:
        print(f"Pending free sign id={result.free_sign_id}")
    else:
        print(f"Blocked: {result.error}")

Web handler example (FastAPI / Flask)
--------------------------------------
    @app.post("/free-sign/propose")
    def propose(body: ProposeRequest, session: Session = Depends(get_session)):
        svc = build_service(session=session)
        result = svc.try_propose(body.manager_id, body.player_id,
                                 posted_at=datetime.now(tz=timezone.utc))
        if not result.success:
            raise HTTPException(status_code=422, detail=result.error)
        return {"free_sign_id": result.free_sign_id}
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fmlwc.core.config import GameRules
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.transfer.free_sign import FreeSignResult, FreeSignService
from fmlwc.persistence.db import create_all, make_engine, make_session_factory


_BATCH_TEMPLATE = """\
# FMLWC 自由签批量导入模板
# 格式：manager_id,player_id[,at]
# - at 列可选；留空则使用运行时 UTC 时间
# - # 开头的行为注释，空行忽略
#
# manager_id  player_id  at (ISO 8601, 可省略)
1,42
2,17,2026-06-04T10:00:00Z
3,99
"""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_service(
    *,
    db_url: str | None = None,
    rules_path: str | None = None,
    session=None,
) -> FreeSignService:
    """Construct a ``FreeSignService`` wired to the SQL backend.

    Parameters
    ----------
    db_url:
        SQLAlchemy URL, e.g. ``"sqlite:///fmlwc.db"``.
        Defaults to reading ``storage.url`` from the rules YAML.
    rules_path:
        Path to the rules YAML file.  Defaults to
        ``config/rules.example.yaml`` in the project root.
    session:
        An existing SQLAlchemy ``Session``.  When provided, ``db_url`` is
        ignored and no session management is done by the factory — the
        caller is responsible for committing and closing.
        Pass this when embedding in a web request context.

    Returns a ``FreeSignService`` whose ``try_propose`` / ``try_revoke`` /
    ``commit_due`` methods are safe to call without a try/except.
    """
    rules = _load_rules(rules_path)

    if session is None:
        url = db_url or rules.storage.url
        engine = make_engine(url)
        create_all(engine)
        _session = make_session_factory(engine)()
        _owns_session = True
    else:
        _session = session
        _owns_session = False

    from fmlwc.persistence.sql_repos import (
        SqlEligibilityRepo,
        SqlFreeSignRepo,
        SqlManagerRepo,
        SqlPlayerRepo,
        SqlTransferRepo,
    )

    mgr_repo  = SqlManagerRepo(_session)
    plr_repo  = SqlPlayerRepo(_session)
    trn_repo  = SqlTransferRepo(_session)
    fs_repo   = SqlFreeSignRepo(_session)
    elig_repo = SqlEligibilityRepo(_session)

    elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)

    svc = FreeSignService(
        rules=rules,
        managers=mgr_repo,
        players=plr_repo,
        transfers=trn_repo,
        free_signs=fs_repo,
        eligibility=elig_svc,
    )

    svc._session = _session        # type: ignore[attr-defined]
    svc._owns_session = _owns_session  # type: ignore[attr-defined]
    return svc


def _load_rules(path: str | None) -> GameRules:
    p = Path(path) if path else ROOT / "config" / "rules.example.yaml"
    return GameRules.from_yaml(p)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_at(s: str | None) -> datetime:
    if s is None:
        return _now()
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Batch CSV parsing
# ---------------------------------------------------------------------------

@dataclass
class BatchRow:
    line_no: int
    manager_id: int
    player_id: int
    at: datetime


@dataclass
class BatchRowError:
    line_no: int
    raw: str
    error: str


def _parse_batch_csv(path: Path) -> tuple[list[BatchRow], list[BatchRowError]]:
    """Parse a batch CSV file into valid rows and parse errors.

    CSV format (no header required):
        manager_id, player_id [, at]

    Lines starting with ``#`` and blank lines are skipped.
    ``at`` is optional; omitting it uses the time the file is parsed.
    """
    rows: list[BatchRow] = []
    errors: list[BatchRowError] = []
    default_at = _now()

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for line_no, raw_cols in enumerate(reader, start=1):
            # Reconstruct raw line for error messages
            raw = ",".join(raw_cols).strip()
            if not raw or raw.startswith("#"):
                continue

            cols = [c.strip() for c in raw_cols]

            try:
                if len(cols) < 2:
                    raise ValueError("need at least manager_id and player_id")
                manager_id = int(cols[0])
                player_id  = int(cols[1])
                at = _parse_at(cols[2] if len(cols) >= 3 and cols[2] else None) \
                     if len(cols) >= 3 else default_at
                rows.append(BatchRow(line_no, manager_id, player_id, at))
            except (ValueError, IndexError) as exc:
                errors.append(BatchRowError(line_no, raw, str(exc)))

    return rows, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="FMLWC free-sign interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", metavar="URL",
                   help="SQLAlchemy DB URL (default: from rules YAML)")
    p.add_argument("--rules", metavar="PATH",
                   help="Rules YAML path (default: config/rules.example.yaml)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # propose
    sp = sub.add_parser("propose", help="Propose a single free sign")
    sp.add_argument("--manager", type=int, required=True, metavar="ID")
    sp.add_argument("--player",  type=int, required=True, metavar="ID")
    sp.add_argument("--at", metavar="ISO8601",
                    help="Timestamp (default: now UTC)")

    # revoke
    sp = sub.add_parser("revoke", help="Revoke a pending free sign")
    sp.add_argument("--id", type=int, required=True, metavar="FREE_SIGN_ID")
    sp.add_argument("--at", metavar="ISO8601",
                    help="Timestamp (default: now UTC)")

    # commit
    sub.add_parser("commit", help="Commit all due free signs").add_argument(
        "--at", metavar="ISO8601", help="Timestamp (default: now UTC)"
    )

    # batch
    sp = sub.add_parser("batch", help="Propose multiple free signs from a CSV file")
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("file", nargs="?", metavar="CSV_FILE",
                     help="Path to the batch CSV file")
    grp.add_argument("--template", action="store_true",
                     help="Print a sample CSV template and exit")

    return p


def main() -> None:
    args = build_parser().parse_args()
    at = _parse_at(getattr(args, "at", None))

    # --template: no DB needed
    if args.cmd == "batch" and args.template:
        print(_BATCH_TEMPLATE, end="")
        return

    svc = build_service(db_url=args.db, rules_path=args.rules)
    session = svc._session   # type: ignore[attr-defined]
    owns    = svc._owns_session  # type: ignore[attr-defined]

    try:
        if args.cmd == "propose":
            result = svc.try_propose(args.manager, args.player, at)
            if result.success:
                print(f"[ok] free sign proposed — id={result.free_sign_id}")
                print(f"     revoke window: {svc.rules.transfer.revoke_window_seconds}s")
            else:
                print(f"[denied] {result.error}")
                sys.exit(1)

        elif args.cmd == "revoke":
            result = svc.try_revoke(args.id, at)
            if result.success:
                print(f"[ok] free sign {args.id} revoked")
            else:
                print(f"[denied] {result.error}")
                sys.exit(1)

        elif args.cmd == "commit":
            count = svc.commit_due(at)
            print(f"[ok] committed {count} free sign(s)")

        elif args.cmd == "batch":
            _run_batch(svc, Path(args.file))

        session.commit()

    except Exception:
        session.rollback()
        raise
    finally:
        if owns:
            session.close()


def _run_batch(svc: FreeSignService, path: Path) -> None:
    """Process a batch CSV: propose each row, print a result table, exit non-zero if any denied."""
    if not path.exists():
        print(f"[error] file not found: {path}", file=sys.stderr)
        sys.exit(1)

    rows, parse_errors = _parse_batch_csv(path)

    if parse_errors:
        print(f"[error] {len(parse_errors)} parse error(s) — fix before retrying:")
        for e in parse_errors:
            print(f"  line {e.line_no}: {e.error!r}  ←  {e.raw!r}")
        sys.exit(1)

    if not rows:
        print("[warn] no data rows found in file")
        return

    ok = denied = 0
    print(f"{'Line':>4}  {'Mgr':>4}  {'Plr':>5}  {'Result'}")
    print("-" * 50)

    for row in rows:
        result = svc.try_propose(row.manager_id, row.player_id, row.at)
        if result.success:
            ok += 1
            print(f"{row.line_no:>4}  {row.manager_id:>4}  {row.player_id:>5}  "
                  f"[ok] id={result.free_sign_id}")
        else:
            denied += 1
            print(f"{row.line_no:>4}  {row.manager_id:>4}  {row.player_id:>5}  "
                  f"[denied] {result.error}")

    print("-" * 50)
    print(f"Total: {len(rows)}  ok={ok}  denied={denied}")

    if denied:
        sys.exit(1)


if __name__ == "__main__":
    main()
