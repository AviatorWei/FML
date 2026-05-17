#!/usr/bin/env python3
"""Generate and persist the initial player list for FMLWC.

Scrapes squad pages from Transfermarkt (or a custom source) and writes
Player rows into the database.  The actual HTTP + HTML parsing inside
``_scrape_team_page`` is a stub — implement it before running this script
against a live site.

Usage
-----
    # Dry-run: print what would be inserted, do not touch the DB
    python scripts/generate_player_list.py --dry-run

    # Sequential IDs, write to default fmlwc.db
    python scripts/generate_player_list.py --id-mode seq

    # IDs from Transfermarkt URLs, custom DB path
    python scripts/generate_player_list.py --id-mode url --db path/to.db

    # Only scrape a subset of teams (comma-separated codes)
    python scripts/generate_player_list.py --teams GER,ENG,FRA --dry-run

Options
-------
    --id-mode {seq,url}   ID assignment strategy (default: seq)
    --db PATH             SQLite database path (default: fmlwc.db in project root)
    --teams CODE,...      Comma-separated team codes to scrape (default: all 24 Euro 2020 teams)
    --seq-start N         First sequential id (default: 1; only used with --id-mode seq)
    --dry-run             Print players to stdout without writing to the database
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fmlwc.io.player_list_generator import (
    EURO_2020_TEAMS,
    IdMode,
    PlayerListGenerator,
    inject_into_session,
    normalise_position,
)
from fmlwc.persistence.db import create_all, make_engine, make_session_factory, session_scope


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate and persist the initial FMLWC player list.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--id-mode",
        choices=["seq", "url"],
        default="seq",
        help="ID strategy: 'seq' for sequential integers, 'url' for Transfermarkt ids (default: seq)",
    )
    p.add_argument(
        "--db",
        default=str(ROOT / "fmlwc.db"),
        metavar="PATH",
        help="SQLite database path (default: %(default)s)",
    )
    p.add_argument(
        "--teams",
        default=None,
        metavar="CODE,...",
        help="Comma-separated team codes to scrape, e.g. GER,ENG,FRA (default: all 24 Euro 2020 teams)",
    )
    p.add_argument(
        "--seq-start",
        type=int,
        default=1,
        metavar="N",
        help="First sequential id to assign (default: 1; ignored when --id-mode url)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print players to stdout without writing to the database",
    )
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # --- resolve team list ---
    if args.teams:
        requested_codes = {c.strip().upper() for c in args.teams.split(",")}
        teams = [t for t in EURO_2020_TEAMS if t.code in requested_codes]
        unknown = requested_codes - {t.code for t in teams}
        if unknown:
            print(f"[warn] unknown team codes ignored: {sorted(unknown)}", file=sys.stderr)
    else:
        teams = EURO_2020_TEAMS

    if not teams:
        print("[error] no teams to scrape", file=sys.stderr)
        sys.exit(1)

    id_mode = IdMode.FROM_URL if args.id_mode == "url" else IdMode.SEQUENTIAL

    print(f"[config] id_mode={id_mode.value}  teams={len(teams)}  db={args.db}")
    print(f"[config] teams: {[t.code for t in teams]}")

    # --- generate ---
    generator = PlayerListGenerator(
        teams=teams,
        id_mode=id_mode,
        seq_start=args.seq_start,
    )

    print("[scrape] calling generator.generate() ...")
    try:
        players = generator.generate()
    except NotImplementedError as exc:
        print(f"\n[stub] {exc}")
        print(
            "\nThe scraper is not yet implemented.  "
            "Open fmlwc/io/player_list_generator.py and fill in "
            "_scrape_team_page() to enable live scraping.\n"
        )
        sys.exit(2)

    print(f"[scrape] got {len(players)} players total")

    # --- dry-run: print table and exit ---
    if args.dry_run:
        _print_table(players)
        return

    # --- inject into DB ---
    url = f"sqlite:///{Path(args.db).resolve()}"
    engine = make_engine(url)
    create_all(engine)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        count = inject_into_session(players, session)

    print(f"[ok] wrote {count} player rows → {args.db}")
    engine.dispose()


def _print_table(players: list) -> None:
    """Pretty-print the player list to stdout (dry-run output)."""
    print(f"\n{'ID':>7}  {'Jersey':>6}  {'Pos':>3}  {'Team':<5}  {'MV':>5}  Name")
    print("-" * 70)
    for pid, raw in players:
        pos = normalise_position(raw.position_raw).value
        jersey = str(raw.jersey_no) if raw.jersey_no is not None else "-"
        mv = f"{raw.market_value_eur_m}m" if raw.market_value_eur_m else "-"
        print(f"{pid:>7}  {jersey:>6}  {pos:>3}  {raw.real_team:<5}  {mv:>5}  {raw.name}")
    print(f"\nTotal: {len(players)} players")


if __name__ == "__main__":
    main()
