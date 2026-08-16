#!/usr/bin/env python3
"""Seed demo match/standings data on top of an auction-populated DB.

Run AFTER scripts/run_auction.py has created managers, players and rosters.
It is idempotent-ish: it clears the match/transfer-window tables it owns and
regenerates them, so re-running gives a fresh deterministic dataset.

    python scripts/seed_demo.py

What it creates
---------------
- transfer_windows  : from rules YAML (needed by the free-sign endpoint)
- group letters     : 16 managers drawn into 4 groups of 4
- gameweeks         : 3 group-stage gameweeks (GW1/GW2 FINALIZED, GW3 LIVE)
- fixtures          : round-robin within each group
- match_results     : deterministic pseudo-random scores for played gameweeks
- player_athletics  : pseudo-random scoring lines for rostered players
- managers.total_points refreshed from results

All randomness is seeded (seed=2024) so output is reproducible.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete

from fmlwc.core.config import GameRules
from fmlwc.core.enums import (
    GameweekPhase,
    GameweekStatus,
    MatchOutcome,
    TransferWindowStatus,
)
from fmlwc.domain.match.schedule import Scheduler
from fmlwc.persistence.db import create_all, make_engine, make_session_factory
from fmlwc.persistence.models.match import (
    Fixture,
    Gameweek,
    MatchResult,
    PlayerAthletics,
)
from fmlwc.persistence.models.people import Manager, RosterEntry
from fmlwc.persistence.models.transfer import TransferWindow

RNG = random.Random(2024)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def main() -> None:
    rules = GameRules.from_yaml(ROOT / "config" / "rules.example.yaml")
    engine = make_engine(rules.storage.url)
    create_all(engine)
    session = make_session_factory(engine)()

    try:
        # -- wipe the tables this script owns --------------------------------
        for model in (MatchResult, Fixture, Gameweek, PlayerAthletics, TransferWindow):
            session.execute(delete(model))
        session.flush()

        # -- transfer windows from rules ------------------------------------
        now = datetime.now(tz=timezone.utc)
        for spec in rules.transfer.windows:
            opens = _naive(spec.opens_at)
            closes = _naive(spec.closes_at)
            status = TransferWindowStatus.PENDING
            n = _naive(now)
            if opens <= n <= closes:
                status = TransferWindowStatus.OPEN
            elif n > closes:
                status = TransferWindowStatus.CLOSED
            session.add(
                TransferWindow(
                    opens_at=opens,
                    closes_at=closes,
                    free_sign_period_seconds=spec.free_sign_period_seconds,
                    status=status,
                )
            )
        session.flush()

        # -- draw groups -----------------------------------------------------
        managers = session.query(Manager).order_by(Manager.id).all()
        mgr_ids = [m.id for m in managers]
        scheduler = Scheduler(rules, seed=7)
        groups = scheduler.draw_groups(mgr_ids)
        letter_of = {}
        for letter, ids in groups.items():
            for mid in ids:
                letter_of[mid] = letter
        for m in managers:
            m.group_letter = letter_of.get(m.id)
        session.flush()

        # -- gameweeks + fixtures -------------------------------------------
        weeks = scheduler.group_stage_fixtures(groups)
        base = datetime(2026, 6, 14, 18, 0)
        gw_rows: list[Gameweek] = []
        for i, _week in enumerate(weeks, start=1):
            if i <= 2:
                status = GameweekStatus.FINALIZED
            elif i == 3:
                status = GameweekStatus.LIVE
            else:
                status = GameweekStatus.PENDING
            gw = Gameweek(
                index=i,
                phase=GameweekPhase.GROUP,
                lineup_deadline=base + timedelta(days=(i - 1) * 4),
                status=status,
            )
            session.add(gw)
            gw_rows.append(gw)
        session.flush()

        points: dict[int, int] = {mid: 0 for mid in mgr_ids}
        for gw, week in zip(gw_rows, weeks):
            for spec in week:
                fx = Fixture(
                    gameweek_id=gw.id,
                    home_manager_id=spec.home_manager_id,
                    away_manager_id=spec.away_manager_id,
                    group_letter=spec.group_letter,
                )
                session.add(fx)
                session.flush()

                if gw.status is GameweekStatus.FINALIZED or (
                    gw.status is GameweekStatus.LIVE and RNG.random() < 0.6
                ):
                    hg = RNG.randint(0, 4)
                    ag = RNG.randint(0, 4)
                    if hg > ag:
                        outcome = MatchOutcome.HOME_WIN
                        points[spec.home_manager_id] += 3
                    elif ag > hg:
                        outcome = MatchOutcome.AWAY_WIN
                        points[spec.away_manager_id] += 3
                    else:
                        outcome = MatchOutcome.DRAW
                        points[spec.home_manager_id] += 1
                        points[spec.away_manager_id] += 1
                    session.add(
                        MatchResult(
                            fixture_id=fx.id,
                            home_goals=hg,
                            away_goals=ag,
                            outcome=outcome,
                            locked_at=_naive(now)
                            if gw.status is GameweekStatus.FINALIZED
                            else None,
                        )
                    )

        for m in managers:
            m.total_points = points.get(m.id, 0)

        # -- player athletics for rostered players --------------------------
        roster_player_ids = sorted(
            {r.player_id for r in session.query(RosterEntry).all()}
        )
        for pid in roster_player_ids:
            # most players score nothing; a minority light up the board
            goals = RNG.choices([0, 0, 0, 1, 1, 2, 3], k=1)[0]
            assists = RNG.choices([0, 0, 0, 1, 2], k=1)[0]
            yellows = RNG.choices([0, 0, 1, 2], k=1)[0]
            reds = RNG.choices([0, 0, 0, 0, 1], k=1)[0]
            if goals == 0 and assists == 0 and yellows == 0 and reds == 0:
                continue
            session.add(
                PlayerAthletics(
                    player_id=pid,
                    goals=goals,
                    assists=assists,
                    yellows=yellows,
                    reds=reds,
                    saved_penalties=RNG.choices([0, 0, 0, 1], k=1)[0],
                )
            )

        session.commit()
        print(
            f"[seed] windows={len(rules.transfer.windows)} "
            f"groups={len(groups)} gameweeks={len(gw_rows)} "
            f"fixtures={session.query(Fixture).count()} "
            f"results={session.query(MatchResult).count()} "
            f"athletics={session.query(PlayerAthletics).count()}"
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
