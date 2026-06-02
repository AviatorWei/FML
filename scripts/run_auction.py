#!/usr/bin/env python3
"""Run one sealed-bid auction round from xlsx files and write results to DB + txt.

Typical usage
-------------
    # Seed players + managers from xlsx, then run round 1
    python scripts/run_auction.py --bids-dir example/bids-1 --round 1 --seed

    # DB already populated; just run the auction
    python scripts/run_auction.py --bids-dir example/bids-1 --round 1

    # Custom DB, custom output directory
    python scripts/run_auction.py --bids-dir example/bids-1 --round 1 \\
        --db sqlite:///my.db --out-dir results/round1/

    # Dry-run: resolve in memory only, write txt but skip DB writes
    python scripts/run_auction.py --bids-dir example/bids-1 --round 1 --dry-run

Output files (in --out-dir, default: output/)
---------------------------------------------
    {N}轮暗标公示.txt    — public bid announcement (all competed bids)
    {N}轮暗标后阵容.txt  — post-auction rosters for every manager

Seeding (--seed)
----------------
    Upserts players and managers from xlsx data so the script is self-contained.
    Players: id/name/real_team/position from each xlsx row.
    Managers: display_name = xlsx filename code (e.g. GER), balance = initial_budget.
    Safe to re-run — upsert is idempotent.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fmlwc.core.config import GameRules
from fmlwc.core.enums import AuctionRoundStatus, Position
from fmlwc.domain.auction.service import AuctionService
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.io.announcement import AuctionAnnouncementFormatter
from fmlwc.io.xlsx_bid_reader import XlsxBidReader
from fmlwc.persistence.db import create_all, make_engine, make_session_factory
from fmlwc.persistence.models.auction import AuctionRound
from fmlwc.persistence.models.people import Manager, Player
from fmlwc.persistence.sql_repos import (
    SqlAuctionResultRepo,
    SqlAuctionRoundRepo,
    SqlBidRepo,
    SqlEligibilityRepo,
    SqlManagerRepo,
    SqlPlayerRepo,
    SqlSubmissionRepo,
    SqlTransferRepo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_rules(path: str | None) -> GameRules:
    p = Path(path) if path else ROOT / "config" / "rules.example.yaml"
    return GameRules.from_yaml(p)


def _parse_at(s: str | None) -> datetime:
    if s is None:
        return datetime.now(tz=timezone.utc)
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _naive(dt: datetime) -> datetime:
    """Strip timezone for SQLite storage (stored as UTC)."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _read_all_players_from_xlsx(bids_dir: Path) -> dict[int, tuple[str, str, str]]:
    """Read every player row in all xlsx files, regardless of whether they were bid on.

    Returns {player_id: (name, real_team, position_str)}.
    When the same player appears in multiple files, the first occurrence wins.
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError("openpyxl is required: pip install openpyxl") from exc

    players: dict[int, tuple[str, str, str]] = {}
    for path in sorted(bids_dir.glob("*.xlsx")):
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        for row in rows[1:]:   # skip header
            if len(row) < 6:
                continue
            pid_raw, name_raw, team_raw, pos_raw = row[2], row[3], row[4], row[5]
            if not isinstance(pid_raw, (int, float)) or pid_raw is None:
                continue
            pid = int(pid_raw)
            if pid == 0 or pid in players:
                continue
            players[pid] = (
                str(name_raw).strip() if name_raw else f"Player{pid}",
                str(team_raw).strip() if team_raw else "UNK",
                str(pos_raw).strip() if pos_raw else "M",
            )
    return players


def seed_from_bids_dir(
    session, bids_dir: Path, submissions, rules: GameRules
) -> dict[str, int]:
    """Upsert ALL players (full xlsx catalog) and managers. Returns code→manager_id map."""
    from sqlalchemy import select

    # Upsert full player catalog — includes players who were never bid on
    players_catalog = _read_all_players_from_xlsx(bids_dir)
    for pid, (name, team, pos_str) in players_catalog.items():
        try:
            position = Position(pos_str)
        except ValueError:
            position = Position.M
        existing = session.get(Player, pid)
        if existing is None:
            session.add(Player(id=pid, name=name, position=position, real_team=team))
        else:
            existing.name = name
            existing.position = position
            existing.real_team = team

    # Upsert managers (by display_name = code)
    codes = sorted({sub.manager_code for sub in submissions})
    budget = rules.managers.initial_budget
    code_to_id: dict[str, int] = {}
    for code in codes:
        stmt = select(Manager).where(Manager.display_name == code)
        mgr = session.scalars(stmt).first()
        if mgr is None:
            mgr = Manager(display_name=code, balance=budget)
            session.add(mgr)
            session.flush()
        code_to_id[code] = mgr.id

    session.flush()
    print(f"[seed] {len(players_catalog)} players, {len(codes)} managers upserted")
    return code_to_id


def resolve_managers(session, submissions) -> dict[str, int]:
    """Look up existing managers in DB by display_name = manager_code."""
    from sqlalchemy import select
    codes = {sub.manager_code for sub in submissions}
    code_to_id: dict[str, int] = {}
    missing = []
    for code in sorted(codes):
        stmt = select(Manager).where(Manager.display_name == code)
        mgr = session.scalars(stmt).first()
        if mgr is None:
            missing.append(code)
        else:
            code_to_id[code] = mgr.id
    if missing:
        print(f"[error] managers not found in DB: {missing}", file=sys.stderr)
        print("        Run with --seed to create them automatically.", file=sys.stderr)
        sys.exit(1)
    return code_to_id


# ---------------------------------------------------------------------------
# Roster formatter
# ---------------------------------------------------------------------------

_POS_ORDER = {Position.G: 0, Position.D: 1, Position.M: 2, Position.F: 3}


def format_rosters(session, manager_codes: list[str], code_to_id: dict[str, int]) -> str:
    """Return post-auction roster text for all managers, sorted by code."""
    blocks: list[str] = []
    for code in sorted(manager_codes):
        mid = code_to_id[code]
        mgr = session.get(Manager, mid)
        mgr_repo = SqlManagerRepo(session)
        plr_repo = SqlPlayerRepo(session)
        roster = mgr_repo.list_roster(mid)

        header = f"{code} {len(roster)}人  剩余资金 {mgr.balance}m"
        lines = [header]

        sorted_roster = sorted(
            roster,
            key=lambda e: (
                _POS_ORDER.get(plr_repo.get(e.player_id).position, 9),
                -e.acquired_price,
            ),
        )
        for entry in sorted_roster:
            player = plr_repo.get(entry.player_id)
            pos = player.position.value
            pid_str = str(player.id)
            gap = " " * max(1, 4 - len(pid_str))
            lines.append(
                f"  {code:<3}  {player.name:<20} {player.real_team:<3}"
                f"  {pid_str}号{gap} {pos}  {entry.acquired_price}m"
            )

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run one auction round from xlsx files; persist to DB and write txt output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--bids-dir", required=True, metavar="DIR",
                   help="Directory containing bid xlsx files")
    p.add_argument("--round", type=int, default=1, metavar="N",
                   help="Auction round index (default: 1)")
    p.add_argument("--db", metavar="URL",
                   help="SQLAlchemy DB URL (default: from rules YAML)")
    p.add_argument("--rules", metavar="PATH",
                   help="Rules YAML path (default: config/rules.example.yaml)")
    p.add_argument("--out-dir", default="output", metavar="DIR",
                   help="Directory for output txt files (default: output/)")
    p.add_argument("--received-at", metavar="ISO8601",
                   help="Timestamp bids were received (default: now UTC)")
    p.add_argument("--closed-at", metavar="ISO8601",
                   help="Timestamp round closed (default: now UTC)")
    p.add_argument("--seed", action="store_true",
                   help="Upsert players + managers from xlsx before running")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve in memory only; write txt but do not commit to DB")
    return p


def main() -> None:
    args = build_parser().parse_args()

    rules = _load_rules(args.rules)
    received_at = _parse_at(args.received_at)
    closed_at   = _parse_at(args.closed_at)
    out_dir     = Path(args.out_dir)
    bids_dir    = Path(args.bids_dir)
    round_index = args.round

    # -- read xlsx files -------------------------------------------------------
    reader = XlsxBidReader(bids_dir)
    submissions = reader.read_all()
    if not submissions:
        print(f"[error] no xlsx bid files found in {bids_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"[load] {len(submissions)} submission files from {bids_dir}")

    # -- DB setup --------------------------------------------------------------
    db_url = args.db or rules.storage.url
    engine = make_engine(db_url)
    create_all(engine)
    session = make_session_factory(engine)()

    try:
        # -- seed if requested -------------------------------------------------
        if args.seed:
            code_to_id = seed_from_bids_dir(session, bids_dir, submissions, rules)
        else:
            code_to_id = resolve_managers(session, submissions)

        # -- guard: refuse to re-run a completed round -------------------------
        from sqlalchemy import select
        existing = session.scalars(
            select(AuctionRound).where(AuctionRound.index == round_index)
        ).first()
        if existing is not None and existing.status is AuctionRoundStatus.CLOSED:
            print(
                f"[error] round {round_index} is already CLOSED in DB. "
                "Reset the DB or use a different --round index.",
                file=sys.stderr,
            )
            sys.exit(1)

        # -- create or reuse the round row -------------------------------------
        if existing is None:
            rnd = AuctionRound(
                index=round_index,
                opens_at=_naive(received_at),
                closes_at=_naive(closed_at),
                status=AuctionRoundStatus.OPEN,
            )
            session.add(rnd)
            session.flush()
            round_id = rnd.id
            print(f"[setup] created auction_round id={round_id} index={round_index}")
        else:
            round_id = existing.id
            print(f"[setup] reusing auction_round id={round_id} index={round_index} "
                  f"(status={existing.status.value})")

        # -- wire service ------------------------------------------------------
        mgr_repo  = SqlManagerRepo(session)
        plr_repo  = SqlPlayerRepo(session)
        sub_repo  = SqlSubmissionRepo(session)
        bid_repo  = SqlBidRepo(session)
        rnd_repo  = SqlAuctionRoundRepo(session)
        res_repo  = SqlAuctionResultRepo(session)
        elig_repo = SqlEligibilityRepo(session)
        trn_repo  = SqlTransferRepo(session)

        elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)
        auction  = AuctionService(
            rules=rules,
            managers=mgr_repo,
            players=plr_repo,
            bids=bid_repo,
            submissions=sub_repo,
            rounds=rnd_repo,
            results=res_repo,
            eligibility_repo=elig_repo,
            eligibility_service=elig_svc,
            transfer_repo=trn_repo,
        )

        # -- open → submit → close → resolve -----------------------------------
        auction.open_round(round_id)

        for sub in submissions:
            mid = code_to_id[sub.manager_code]
            raw_bids = sub.to_raw_bids(mid)
            auction.submit(round_id, mid, raw_bids, received_at,
                           source_file=sub.source_file)
        print(f"[submit] {len(submissions)} bid sheets submitted")

        auction.close_round(round_id, at=closed_at)
        resolution = auction.resolve(round_id, at=closed_at)
        print(
            f"[resolve] {len(resolution.awards)} awards, "
            f"{resolution.invalidated} cascade-invalidated, "
            f"total spend {resolution.total_spend}m"
        )

        # -- generate output text ----------------------------------------------
        views = auction.announcement_views(round_id)
        ann_text = AuctionAnnouncementFormatter().format(views)

        manager_codes = [sub.manager_code for sub in submissions]
        roster_text = format_rosters(session, manager_codes, code_to_id)

        # -- write txt files ---------------------------------------------------
        out_dir.mkdir(parents=True, exist_ok=True)
        ann_path    = out_dir / f"{round_index}轮暗标公示.txt"
        roster_path = out_dir / f"{round_index}轮暗标后阵容.txt"

        ann_path.write_text(ann_text, encoding="utf-8")
        roster_path.write_text(roster_text, encoding="utf-8")
        print(f"[output] {ann_path}")
        print(f"[output] {roster_path}")

        # -- commit or rollback ------------------------------------------------
        if args.dry_run:
            session.rollback()
            print("[dry-run] rolled back — DB unchanged")
        else:
            session.commit()
            print(f"[ok] round {round_index} committed to {db_url}")

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
