#!/usr/bin/env python3
"""Initialise (or reset) the SQLite database file.

Usage:
    python scripts/init_db.py              # creates fmlwc.db in project root
    python scripts/init_db.py path/to.db  # custom path
    python scripts/init_db.py --reset     # drop and recreate fmlwc.db
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fmlwc.persistence.db import create_all, make_engine


def main() -> None:
    args = sys.argv[1:]
    reset = "--reset" in args
    args = [a for a in args if a != "--reset"]

    db_path = Path(args[0]) if args else ROOT / "fmlwc.db"

    if reset and db_path.exists():
        db_path.unlink()
        print(f"[reset] removed {db_path}")

    url = f"sqlite:///{db_path.resolve()}"
    engine = make_engine(url)
    create_all(engine)
    engine.dispose()

    print(f"[ok] schema created → {db_path.resolve()}")
    print("     open with:  sqlite3", db_path)


if __name__ == "__main__":
    main()
