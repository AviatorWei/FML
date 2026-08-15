"""Lineup input — validation preview + deadline-checked submission.

Manager-facing: no admin token required for validate/submit (the real
deployment would authenticate managers; server still enforces deadline
and roster checks through the engine's ``LineupValidator``).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from fmlwc.core.enums import GameweekStatus, Position
from fmlwc.core.exceptions import LineupError
from fmlwc.domain.lineup.validator import LineupValidator, StarterInput
from fmlwc.persistence.models.match import Fixture, Gameweek, Lineup
from fmlwc.persistence.models.people import Manager, Player
from fmlwc.persistence.sql_repos import SqlFixtureRepo, SqlManagerRepo, SqlPlayerRepo

from .deps import RULES, SessionFactory, naive, now_utc

router = APIRouter(prefix="/api/lineups", tags=["lineups"])


class StarterIn(BaseModel):
    player_id: int
    slot_position: str  # "G" | "D" | "M" | "F"


class LineupIn(BaseModel):
    manager_id: int
    starters: list[StarterIn]
    pk_order: list[int] | None = None
    gameweek: int | None = None  # optional on /validate — enables cup checks


def _to_starter_inputs(starters: list[StarterIn]) -> list[StarterInput]:
    out = []
    for st in starters:
        try:
            pos = Position(st.slot_position)
        except ValueError:
            raise HTTPException(status_code=422,
                                detail=f"Bad slot position {st.slot_position!r} (use G/D/M/F).")
        out.append(StarterInput(player_id=st.player_id, slot_position=pos))
    return out


class _CupRosterManagerRepo(SqlManagerRepo):
    """ManagerRepo view whose roster is the forked cup list.

    Used to validate CUP lineups after separation (第七十七条): the pool of
    legal starters is the manager's independent cup roster, not the league
    roster."""

    def list_roster(self, manager_id: int):
        from fmlwc.persistence.models.competition import CupRosterEntry
        return list(self.s.scalars(
            select(CupRosterEntry)
            .where(CupRosterEntry.manager_id == manager_id)
            .where(CupRosterEntry.released_at.is_(None))))


def _validate(s, manager_id: int, starters: list[StarterInput],
              gw: Gameweek | None = None) -> dict:
    from fmlwc.core.enums import Competition
    from .cup import separation_active

    mgr_repo = SqlManagerRepo(s)
    if (gw is not None and gw.competition is Competition.CUP
            and separation_active(s)):
        mgr_repo = _CupRosterManagerRepo(s)
    validator = LineupValidator(RULES, SqlPlayerRepo(s), mgr_repo)
    try:
        result = validator.validate(manager_id, starters)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=f"LineupValidator not implemented: {exc}")
    except LineupError as exc:
        return {"valid": False, "error": str(exc), "accepted": [], "dropped": []}
    return {
        "valid": True, "error": None,
        "accepted": [{"player_id": a.player_id, "slot_position": a.slot_position.value}
                     for a in result.accepted],
        "dropped": [{"player_id": d.player_id, "reason": d.reason}
                    for d in result.dropped],
    }


@router.get("/constraints")
def constraints() -> dict:
    """Lineup rules for the UI — nothing is hardcoded client-side."""
    cfg = RULES.lineup
    return {
        "positions": [p.value for p in Position],
        "starters_min": cfg.starters_min,
        "starters_max": cfg.starters_max,
        "appearance_caps": {p.value: c for p, c in cfg.appearance_caps.items()},
        "group_caps": [
            {"positions": [p.value for p in ps], "max": cap}
            for ps, cap in cfg.group_caps
        ],
        "must_have_positions": [p.value for p in cfg.must_have_positions],
        "backward_substitution": {
            p.value: [q.value for q in qs]
            for p, qs in cfg.backward_substitution.items()
        },
    }


@router.post("/validate")
def validate_lineup(req: LineupIn) -> dict:
    from .cup import check_starters_cup

    with SessionFactory() as s:
        if s.get(Manager, req.manager_id) is None:
            raise HTTPException(status_code=404, detail="Manager not found.")
        gw = None
        if req.gameweek is not None:
            gw = s.scalars(select(Gameweek).where(Gameweek.index == req.gameweek)).first()
        verdict = _validate(s, req.manager_id, _to_starter_inputs(req.starters), gw)
        # Cup eligibility preview when the target gameweek is known.
        verdict["cup_blocked"] = []
        if gw is not None:
            verdict["cup_blocked"] = check_starters_cup(
                s, req.manager_id, gw.competition,
                [st.player_id for st in req.starters])
        return verdict


@router.get("")
def list_lineups(gameweek: int | None = None) -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        pnames = {p.id: p.name for p in s.scalars(select(Player))}
        gws = {g.id: g for g in s.scalars(select(Gameweek))}
        fixtures = {f.id: f for f in s.scalars(select(Fixture))}
        out = []
        for lu in s.scalars(select(Lineup).order_by(Lineup.fixture_id, Lineup.manager_id)):
            fx = fixtures.get(lu.fixture_id)
            gw = gws.get(fx.gameweek_id) if fx else None
            if gameweek is not None and (gw is None or gw.index != gameweek):
                continue
            out.append({
                "fixture_id": lu.fixture_id,
                "gameweek": gw.index if gw else None,
                "competition": gw.competition.value if gw else None,
                "manager_id": lu.manager_id,
                "manager": names.get(lu.manager_id),
                "starters": [
                    {**st, "player_name": pnames.get(st.get("player_id"))}
                    for st in (lu.starters or [])
                ],
                "pk_order": lu.pk_order,
                "posted_at": lu.posted_at.isoformat(),
            })
    return {"lineups": out}


@router.put("/{gameweek_index}/{manager_id}")
def submit_lineup(gameweek_index: int, manager_id: int, req: LineupIn) -> dict:
    """Upsert a lineup for the manager's fixture in the given gameweek.

    Server-side checks: gameweek exists and is PENDING (before deadline),
    manager has a fixture, lineup passes ``LineupValidator``.
    """
    at = naive(now_utc())
    with SessionFactory() as s:
        gw = s.scalars(select(Gameweek).where(Gameweek.index == gameweek_index)).first()
        if gw is None:
            raise HTTPException(status_code=404, detail=f"Gameweek {gameweek_index} not found.")
        if gw.status is not GameweekStatus.PENDING:
            raise HTTPException(status_code=409,
                                detail=f"Gameweek is {gw.status.value}; lineups are locked.")
        if gw.lineup_deadline and at > gw.lineup_deadline:
            raise HTTPException(status_code=409,
                                detail=f"Lineup deadline passed ({gw.lineup_deadline.isoformat()}).")
        fixture = s.scalars(
            select(Fixture).where(Fixture.gameweek_id == gw.id)
            .where((Fixture.home_manager_id == manager_id)
                   | (Fixture.away_manager_id == manager_id))
        ).first()
        if fixture is None:
            raise HTTPException(status_code=404,
                                detail="Manager has no fixture in this gameweek.")

        starters = _to_starter_inputs(req.starters)
        verdict = _validate(s, manager_id, starters, gw)
        if not verdict["valid"]:
            raise HTTPException(status_code=422, detail=verdict["error"])

        # Cup eligibility (dual-competition mode): hard-block ineligible starters.
        from .cup import check_starters_cup
        cup_blocked = check_starters_cup(
            s, manager_id, gw.competition, [st.player_id for st in starters])
        if cup_blocked:
            raise HTTPException(
                status_code=422,
                detail="Cup eligibility: " + "; ".join(
                    f"{b['player']}: {b['reason']}" for b in cup_blocked))

        if req.pk_order:
            starter_ids = {st.player_id for st in starters}
            bad = [pid for pid in req.pk_order if pid not in starter_ids]
            if bad:
                raise HTTPException(status_code=422,
                                    detail=f"pk_order contains non-starters: {bad}")

        SqlFixtureRepo(s).save_lineup(
            fixture.id, manager_id,
            starters=[{"player_id": st.player_id, "slot_position": st.slot_position.value}
                      for st in starters],
            posted_at=at,
            pk_order=req.pk_order,
        )
        s.commit()
        return {"ok": True, "fixture_id": fixture.id, "posted_at": at.isoformat(), **verdict}
