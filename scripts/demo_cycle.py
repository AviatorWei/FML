"""End-to-end demo: walk one mini-season in-memory.

Run:
    python scripts/demo_cycle.py config/rules.example.yaml

Skeleton-stage behaviour:
    every step prints the action it intends to take. Once service methods
    are implemented, the same script will produce real auction results,
    rosters, fixtures, and a final standings table.

Imports demonstrate the new layered layout:
    fmlwc.core           — enums, exceptions, config
    fmlwc.persistence    — engine, models, repositories
    fmlwc.domain.*       — business services
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(yaml_path: str) -> None:
    print(f"[load] reading rules from {yaml_path}")
    # from fmlwc.core import GameRules
    # rules = GameRules.from_yaml(yaml_path)

    print("[setup] init in-memory SQLite, create_all schema")
    # from fmlwc.persistence import make_engine, make_session_factory, create_all
    # engine = make_engine("sqlite:///:memory:")
    # create_all(engine)
    # factory = make_session_factory(engine)

    print("[setup] seed 16 managers with starting balance")
    print("[setup] load reduced player list (e.g. 50 sample players)")

    print("[auction] open round 1")
    # from fmlwc.domain.auction import AuctionService
    # auction.open_round(round_id=1)

    print("[auction] M01 / M02 / M03 submit hand-crafted bid sheets")
    print("[auction] close round 1, run cascade + tiebreaker, print awards")

    print("[transfer] open window 1 — demo 1 free_sign + 1 trade + 1 release")
    # from fmlwc.domain.transfer import FreeSignService, TradeService, ReleaseService

    print("[match] draw groups, build group-stage fixtures")
    # from fmlwc.domain.match import Scheduler

    print("[match] manager submits lineup for gameweek 1")
    # from fmlwc.domain.lineup import LineupValidator

    print("[match] importer ingests real-world events for gameweek 1")
    # from fmlwc.domain.match import ManualImporter

    print("[match] settle gameweek 1, print standings")
    # from fmlwc.domain.season import SeasonOrchestrator

    print("[done] demo flow walkthrough finished — implement service bodies to see real numbers")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(str(Path(__file__).parent.parent / "config" / "rules.example.yaml"))
