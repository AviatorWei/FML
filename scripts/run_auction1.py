#!/usr/bin/env python3
"""Run auction round 1 from bids-1/ xlsx files and compare with expected output.

Usage:
    python scripts/run_auction1.py
"""

from __future__ import annotations

import sys
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fmlwc.core.enums import AuctionRoundStatus, Position
from fmlwc.domain.auction.service import AuctionService
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.io.announcement import AuctionAnnouncementFormatter
from fmlwc.io.xlsx_bid_reader import XlsxBidReader
from tests.fakes import FakeAuctionRound, FakeManager, FakePlayer, make_auction_repos
from tests.sample_rules import default_rules


# ---------------------------------------------------------------------------
# Helpers: parse expected announcement txt
# ---------------------------------------------------------------------------

@dataclass
class ExpectedBidLine:
    rank: int
    amount: int
    player_name: str
    position: str
    real_team: str
    player_id: int
    manager_code: str


def parse_expected_announcement(text: str) -> list[ExpectedBidLine]:
    """Parse lines like '1   10m  Neuer               G  GER         1号  ITA'."""
    lines = []
    pattern = re.compile(
        r'^(\d+)\s+(\d+)m\s+(\S+)\s+([GDMF])\s+([A-Z]+)\s+(\d+)号\s+([A-Z]+)\s*$'
    )
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = pattern.match(raw)
        if m:
            lines.append(ExpectedBidLine(
                rank=int(m.group(1)),
                amount=int(m.group(2)),
                player_name=m.group(3),
                position=m.group(4),
                real_team=m.group(5),
                player_id=int(m.group(6)),
                manager_code=m.group(7),
            ))
    return lines


@dataclass
class ExpectedRosterEntry:
    manager_code: str
    player_name: str
    real_team: str
    player_id: int
    position: str
    amount: int


@dataclass
class ExpectedRoster:
    manager_code: str
    player_count: int
    remaining_balance: int
    entries: list[ExpectedRosterEntry]


def parse_expected_roster(text: str) -> list[ExpectedRoster]:
    """Parse roster blocks like:
        NED 6人                             剩余资金 507m
        Jasper
        NED  Costa               POR            592号   G   10m
    """
    rosters: list[ExpectedRoster] = []
    current: ExpectedRoster | None = None

    header_pat = re.compile(r'^([A-Z]+)\s+(\d+)人.*剩余资金\s+(\d+)m')
    entry_pat = re.compile(
        r'^([A-Z]+)\s+(\S+)\s+([A-Z]+)\s+(\d+)号\s+([GDMF])\s+(\d+)m'
    )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = header_pat.match(line)
        if m:
            if current is not None:
                rosters.append(current)
            current = ExpectedRoster(
                manager_code=m.group(1),
                player_count=int(m.group(2)),
                remaining_balance=int(m.group(3)),
                entries=[],
            )
            continue

        if current is None:
            continue

        m2 = entry_pat.match(line)
        if m2:
            current.entries.append(ExpectedRosterEntry(
                manager_code=m2.group(1),
                player_name=m2.group(2),
                real_team=m2.group(3),
                player_id=int(m2.group(4)),
                position=m2.group(5),
                amount=int(m2.group(6)),
            ))

    if current is not None:
        rosters.append(current)

    return rosters


# ---------------------------------------------------------------------------
# Roster output formatter
# ---------------------------------------------------------------------------

def format_roster(manager_code, manager, roster, plr_repo) -> str:
    lines = [f"{manager_code} {len(roster)}人  剩余资金 {manager.balance}m"]
    # Sort by position order G, D, M, F then by amount desc
    pos_order = {Position.G: 0, Position.D: 1, Position.M: 2, Position.F: 3}
    sorted_roster = sorted(
        roster,
        key=lambda e: (pos_order[plr_repo.get(e.player_id).position], -e.acquired_price),
    )
    for entry in sorted_roster:
        player = plr_repo.get(entry.player_id)
        pos = player.position.value
        lines.append(
            f"  {manager_code:<3}  {player.name:<20} {player.real_team:<4}  "
            f"{player.id}号  {pos}  {entry.acquired_price}m"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    project_root = Path(__file__).parent.parent
    bids_dir = project_root / "example" / "bids-1"

    # --- 1. Read all xlsx files ---
    reader = XlsxBidReader(bids_dir)
    submissions = reader.read_all()
    print(f"[load] read {len(submissions)} submission files from {bids_dir}")

    # --- 2. Build player database from all bid rows ---
    players_by_id: dict[int, tuple[str | None, str | None, str | None]] = {}
    for sub in submissions:
        for row in sub.rows:
            if row.player_id not in players_by_id:
                players_by_id[row.player_id] = (row.player_name, row.real_team, row.position_str)

    print(f"[setup] found {len(players_by_id)} unique players across all bids")

    # --- 3. Manager mapping (alphabetical code → integer id) ---
    manager_codes = sorted({sub.manager_code for sub in submissions})
    code_to_id = {code: i + 1 for i, code in enumerate(manager_codes)}
    print(f"[setup] managers ({len(manager_codes)}): {manager_codes}")

    # --- 4. Build fake repos ---
    managers_list = [
        FakeManager(id=code_to_id[code], display_name=code, balance=600)
        for code in manager_codes
    ]
    players_list = [
        FakePlayer(
            id=pid,
            name=name or f"Player{pid}",
            position=Position(pos) if pos in ("G", "D", "M", "F") else Position.M,
            real_team=team or "UNK",
        )
        for pid, (name, team, pos) in players_by_id.items()
    ]

    rules = default_rules()

    (mgr_repo, plr_repo, elig_repo,
     sub_repo, bid_repo, rnd_repo, res_repo, trn_repo) = make_auction_repos(
        managers=managers_list, players=players_list
    )

    elig_service = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)

    auction = AuctionService(
        rules=rules,
        managers=mgr_repo,
        players=plr_repo,
        bids=bid_repo,
        submissions=sub_repo,
        rounds=rnd_repo,
        results=res_repo,
        eligibility_repo=elig_repo,
        eligibility_service=elig_service,
        transfer_repo=trn_repo,
    )

    # --- 5. Open round 1 ---
    round_id = 1
    rnd_repo.add(FakeAuctionRound(
        id=round_id, index=1,
        opens_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        closes_at=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
    ))
    auction.open_round(round_id)

    # --- 6. Submit bids (all at same time — tiebreaker uses draw seed for same-time ties) ---
    received_at = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    for sub in submissions:
        mid = code_to_id[sub.manager_code]
        raw_bids = sub.to_raw_bids(mid)
        auction.submit(round_id, mid, raw_bids, received_at, source_file=sub.source_file)
    print(f"[submit] submitted {len(submissions)} bid sheets")

    # --- 7. Close and resolve ---
    close_at = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    auction.close_round(round_id, at=close_at)
    resolution = auction.resolve(round_id, at=close_at)
    print(f"[resolve] {len(resolution.awards)} awards, {resolution.invalidated} cascade-invalidated, total spend {resolution.total_spend}m")

    # --- 8. Generate announcement ---
    views = auction.announcement_views(round_id)
    generated_announcement = AuctionAnnouncementFormatter().format(views)

    # --- 9. Generate roster text ---
    roster_lines: list[str] = []
    for code in manager_codes:
        mid = code_to_id[code]
        roster = mgr_repo.list_roster(mid)
        manager = mgr_repo.get(mid)
        roster_lines.append(format_roster(code, manager, roster, plr_repo))
    generated_roster = "\n\n".join(roster_lines)

    # --- 10. Compare with expected ---
    expected_ann_path = project_root / "example" / "1轮暗标公示.txt"
    expected_ros_path = project_root / "example" / "1轮暗标后阵容.txt"

    expected_ann_text = expected_ann_path.read_text(encoding="utf-8")
    expected_ros_text = expected_ros_path.read_text(encoding="utf-8")

    expected_bids = parse_expected_announcement(expected_ann_text)
    expected_rosters = parse_expected_roster(expected_ros_text)

    print("\n" + "=" * 70)
    print("ANNOUNCEMENT COMPARISON")
    print("=" * 70)

    # Build lookup: (player_id, manager_code) -> ExpectedBidLine
    expected_bid_map = {(b.player_id, b.manager_code): b for b in expected_bids}

    # Build lookup from generated views
    gen_bid_map = {(v.player_id, v.manager_code): v for v in views}

    ann_ok = True
    for key, exp in sorted(expected_bid_map.items()):
        gen = gen_bid_map.get(key)
        if gen is None:
            print(f"  MISSING in generated: {key} — expected rank={exp.rank}, amount={exp.amount}m")
            ann_ok = False
        elif gen.amount != exp.amount or gen.rank_in_position != exp.rank:
            print(f"  MISMATCH {key}: expected rank={exp.rank}, amount={exp.amount}m | "
                  f"got rank={gen.rank_in_position}, amount={gen.amount}m")
            ann_ok = False

    for key, gen in sorted(gen_bid_map.items()):
        if key not in expected_bid_map:
            print(f"  EXTRA in generated: {key} — rank={gen.rank_in_position}, amount={gen.amount}m")
            ann_ok = False

    if ann_ok:
        print("  OK — all bid lines match (player_id, manager_code, rank, amount)")
    else:
        print("\n--- GENERATED ANNOUNCEMENT ---")
        print(generated_announcement)

    print("\n" + "=" * 70)
    print("ROSTER COMPARISON")
    print("=" * 70)

    expected_roster_map = {r.manager_code: r for r in expected_rosters}
    roster_ok = True

    for code in manager_codes:
        mid = code_to_id[code]
        roster = mgr_repo.list_roster(mid)
        manager = mgr_repo.get(mid)

        exp_ros = expected_roster_map.get(code)
        if exp_ros is None:
            print(f"  MISSING expected roster for {code}")
            roster_ok = False
            continue

        if len(roster) != exp_ros.player_count:
            print(f"  {code}: roster count {len(roster)} != expected {exp_ros.player_count}")
            roster_ok = False

        if manager.balance != exp_ros.remaining_balance:
            print(f"  {code}: balance {manager.balance}m != expected {exp_ros.remaining_balance}m")
            roster_ok = False

        gen_pids = {e.player_id for e in roster}
        exp_pids = {e.player_id for e in exp_ros.entries}

        missing = exp_pids - gen_pids
        extra = gen_pids - exp_pids
        if missing:
            print(f"  {code}: missing players {sorted(missing)}")
            roster_ok = False
        if extra:
            print(f"  {code}: extra players {sorted(extra)}")
            roster_ok = False

        for exp_entry in exp_ros.entries:
            gen_entry = next((e for e in roster if e.player_id == exp_entry.player_id), None)
            if gen_entry and gen_entry.acquired_price != exp_entry.amount:
                print(f"  {code}: player {exp_entry.player_id} ({exp_entry.player_name}) "
                      f"price {gen_entry.acquired_price}m != expected {exp_entry.amount}m")
                roster_ok = False

    if roster_ok:
        print("  OK — all roster entries match (player, balance, price)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if ann_ok and roster_ok:
        print("  PASS — auction output matches expected for round 1")
    else:
        print("  FAIL — see differences above")

    # Always print generated outputs for inspection
    print("\n--- GENERATED ANNOUNCEMENT ---")
    print(generated_announcement)
    print("\n--- GENERATED ROSTERS ---")
    print(generated_roster)


if __name__ == "__main__":
    main()
