#!/usr/bin/env python3
"""Export the player list from the database to an xlsx spreadsheet.

Usage
-----
    python scripts/export_players.py                        # player_list.xlsx from fmlwc.db
    python scripts/export_players.py --db path/to.db       # custom DB
    python scripts/export_players.py --out players.xlsx     # custom output path
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fmlwc.io.player_list_exporter import PlayerListExporter, query_player_list
from fmlwc.persistence.db import make_engine, make_session_factory, session_scope


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export FMLWC player list to xlsx.")
    p.add_argument("--db", default=str(ROOT / "fmlwc.db"), metavar="PATH",
                   help="SQLite database path (default: fmlwc.db)")
    p.add_argument("--out", default="player_list.xlsx", metavar="PATH",
                   help="Output xlsx path (default: player_list.xlsx)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    url = f"sqlite:///{Path(args.db).resolve()}"
    engine = make_engine(url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        rows = query_player_list(session)

    engine.dispose()

    if not rows:
        print("[warn] no players found in database — is the DB initialised?", file=sys.stderr)
        sys.exit(1)

    PlayerListExporter().write(rows, args.out)
    print(f"[ok] exported {len(rows)} players → {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
