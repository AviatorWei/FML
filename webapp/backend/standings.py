"""Standings computation shared by the public API and exports."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fmlwc.core.enums import Competition
from fmlwc.persistence.models.match import Fixture, Gameweek, MatchResult
from fmlwc.persistence.models.people import Manager


def blank_row(m: Manager) -> dict:
    return {
        "manager_id": m.id,
        "name": m.display_name,
        "group": m.group_letter,
        "played": 0, "win": 0, "draw": 0, "loss": 0,
        "gf": 0, "ga": 0, "gd": 0, "points": 0,
    }


def compute_standings(
    s: Session, competition: Competition | None = None
) -> dict[int, dict]:
    """Aggregate results into a table. When *competition* is given, only
    results from gameweeks of that competition count (dual-competition mode)."""
    managers = s.scalars(select(Manager)).all()
    rows = {m.id: blank_row(m) for m in managers}

    q = select(MatchResult, Fixture).join(Fixture, MatchResult.fixture_id == Fixture.id)
    if competition is not None:
        q = (q.join(Gameweek, Fixture.gameweek_id == Gameweek.id)
             .where(Gameweek.competition == competition))
    for res, fx in s.execute(q).all():
        h, a = fx.home_manager_id, fx.away_manager_id
        if h not in rows or a not in rows:
            continue
        rows[h]["played"] += 1
        rows[a]["played"] += 1
        rows[h]["gf"] += res.home_goals
        rows[h]["ga"] += res.away_goals
        rows[a]["gf"] += res.away_goals
        rows[a]["ga"] += res.home_goals
        if res.home_goals > res.away_goals:
            rows[h]["win"] += 1
            rows[a]["loss"] += 1
            rows[h]["points"] += 3
        elif res.away_goals > res.home_goals:
            rows[a]["win"] += 1
            rows[h]["loss"] += 1
            rows[a]["points"] += 3
        else:
            rows[h]["draw"] += 1
            rows[a]["draw"] += 1
            rows[h]["points"] += 1
            rows[a]["points"] += 1

    for r in rows.values():
        r["gd"] = r["gf"] - r["ga"]
    return rows


def sort_table(rows: list[dict]) -> list[dict]:
    ordered = sorted(rows, key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
    for i, r in enumerate(ordered, start=1):
        r["rank"] = i
    return ordered
