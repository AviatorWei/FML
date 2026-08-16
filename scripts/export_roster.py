#!/usr/bin/env python3
"""Export current rosters to stdout in the display format.

Usage:
    python scripts/export_roster.py
    python scripts/export_roster.py --db path/to/other.db
    python scripts/export_roster.py --out roster.txt
    python scripts/export_roster.py --manager AFC
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from fmlwc.persistence.db import make_engine, make_session_factory
from fmlwc.persistence.models.people import Manager, Player, RosterEntry

POS_ORDER = {"G": 0, "D": 1, "M": 2, "W": 3, "F": 4}
HEADER_COL = 46  # target display column where 剩余资金 starts


def _display_width(s: str) -> int:
    """Display width: CJK/wide chars count as 2 columns."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def format_header(code: str, n: int, balance: int) -> str:
    left = f"{code} {n}人"
    spaces = HEADER_COL - _display_width(left)
    return left + " " * max(1, spaces) + f"剩余资金 {balance}"


def format_player(code: str, pos: str, pid: int, name: str, team: str, price: int) -> str:
    team_compact = team.replace(" ", "")
    return f"{code} {pos} {pid:>6}号 {name:<19}{team_compact:<21}{price}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export current rosters")
    parser.add_argument("--db", default="fmlwc.db", help="SQLite DB path")
    parser.add_argument("--out", default=None, help="Output file (default: stdout)")
    parser.add_argument("--manager", default=None, help="Filter to one manager code")
    args = parser.parse_args()

    db_path = Path(args.db) if not args.db.startswith("sqlite://") else None
    db_url = args.db if args.db.startswith("sqlite://") else f"sqlite:///{Path(args.db).resolve()}"

    engine = make_engine(db_url)
    SessionFactory = make_session_factory(engine)

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout

    try:
        with SessionFactory() as s:
            stmt = select(Manager).order_by(Manager.group_letter, Manager.display_name)
            if args.manager:
                stmt = stmt.where(Manager.display_name == args.manager)
            managers = s.scalars(stmt).all()

            players_by_id = {p.id: p for p in s.scalars(select(Player)).all()}

            first = True
            for mgr in managers:
                entries = s.scalars(
                    select(RosterEntry).where(
                        RosterEntry.manager_id == mgr.id,
                        RosterEntry.released_at.is_(None),
                    )
                ).all()

                if not entries:
                    continue

                entries_sorted = sorted(
                    entries,
                    key=lambda e: (
                        POS_ORDER.get(players_by_id[e.player_id].position.value, 99),
                        players_by_id[e.player_id].name,
                    ),
                )

                if not first:
                    print(file=out)
                first = False

                print(format_header(mgr.display_name, len(entries), mgr.balance), file=out)
                print(mgr.manager_name or "", file=out)

                for entry in entries_sorted:
                    p = players_by_id[entry.player_id]
                    print(
                        format_player(
                            mgr.display_name,
                            p.position.value,
                            p.id,
                            p.name,
                            p.real_team,
                            entry.acquired_price or 0,
                        ),
                        file=out,
                    )
    finally:
        if args.out:
            out.close()
            print(f"Written to {args.out}", file=sys.stderr)

    engine.dispose()


if __name__ == "__main__":
    main()
