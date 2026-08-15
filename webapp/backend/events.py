"""Match-event input — single events, bulk CSV import, live tally preview.

Events are keyed by (gameweek, player); ``RoundService`` enforces the
gameweek must be LIVE for add/remove.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from fmlwc.core.enums import RealEventType
from fmlwc.core.exceptions import MatchError
from fmlwc.domain.match.round import RoundService
from fmlwc.domain.match.scoring import ValidGoalCalculator
from fmlwc.persistence.models.match import Fixture, Gameweek, MatchEvent
from fmlwc.persistence.models.people import Manager, Player
from fmlwc.persistence.sql_repos import (
    SqlAthleticsRepo,
    SqlFixtureRepo,
    SqlGameweekRepo,
    SqlManagerRepo,
    SqlMatchEventRepo,
)

from .deps import RULES, SessionFactory, require_admin

router = APIRouter(prefix="/api/admin/events", tags=["admin:events"],
                   dependencies=[Depends(require_admin)])


def _round_service(s) -> RoundService:
    return RoundService(
        rules=RULES,
        gameweeks=SqlGameweekRepo(s),
        fixtures=SqlFixtureRepo(s),
        events=SqlMatchEventRepo(s),
        athletics=SqlAthleticsRepo(s),
        managers=SqlManagerRepo(s),
    )


def _gw_by_index(s, index: int) -> Gameweek:
    gw = s.scalars(select(Gameweek).where(Gameweek.index == index)).first()
    if gw is None:
        raise HTTPException(status_code=404, detail=f"Gameweek {index} not found.")
    return gw


def _parse_event_type(value: str) -> RealEventType:
    try:
        return RealEventType(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Bad event_type {value!r}. One of: "
                   + ", ".join(t.value for t in RealEventType))


class EventIn(BaseModel):
    gameweek: int  # gameweek index (not id)
    player_id: int
    event_type: str
    minute: int | None = None
    is_extra_time: bool = False
    is_shootout: bool = False


def _warnings(s, gw: Gameweek, player: Player, etype: RealEventType,
              is_shootout: bool) -> list[str]:
    w = []
    if etype is RealEventType.SAVED_PENALTY_BY_GK and player.position.value != "G":
        w.append(f"{player.name} is a {player.position.value}, not a GK — check event type.")
    if is_shootout:
        w.append("Shootout events are excluded from FME goal counting (rule 零.4).")
    starter_map = SqlFixtureRepo(s).player_manager_map(gw.id)
    if player.id not in starter_map:
        w.append(f"{player.name} is not in any submitted lineup this gameweek — "
                 "the event won't score for any manager.")
    return w


@router.get("")
def list_events(gameweek: int = Query(...)) -> dict:
    with SessionFactory() as s:
        gw = _gw_by_index(s, gameweek)
        pnames = {p.id: p.name for p in s.scalars(select(Player))}
        rows = s.scalars(
            select(MatchEvent).where(MatchEvent.gameweek_id == gw.id)
            .order_by(MatchEvent.id.desc())
        ).all()
        out = [
            {"id": e.id, "player_id": e.player_id, "player": pnames.get(e.player_id),
             "event_type": e.event_type.value, "minute": e.minute,
             "is_extra_time": e.is_extra_time, "is_shootout": e.is_shootout}
            for e in rows
        ]
    return {"gameweek": gameweek, "status": gw.status.value, "events": out}


@router.post("")
def add_event(req: EventIn) -> dict:
    etype = _parse_event_type(req.event_type)
    with SessionFactory() as s:
        gw = _gw_by_index(s, req.gameweek)
        player = s.get(Player, req.player_id)
        if player is None:
            raise HTTPException(status_code=404, detail="Player not found.")
        try:
            event_id = _round_service(s).add_event(
                gw.id, req.player_id, etype,
                minute=req.minute, is_extra_time=req.is_extra_time,
                is_shootout=req.is_shootout)
        except MatchError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        warnings = _warnings(s, gw, player, etype, req.is_shootout)
        s.commit()
        return {"ok": True, "event_id": event_id, "warnings": warnings}


@router.delete("/{event_id}")
def delete_event(event_id: int) -> dict:
    with SessionFactory() as s:
        ev = s.get(MatchEvent, event_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="Event not found.")
        try:
            _round_service(s).remove_event(ev.gameweek_id, event_id)
        except MatchError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        s.commit()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Bulk CSV import (round-trips with /api/export/events.csv)
# ---------------------------------------------------------------------------

@router.post("/import")
async def import_events(file: UploadFile = File(...), dry_run: bool = Query(True)) -> dict:
    """CSV columns: gameweek, player_id, event_type, minute, is_extra_time, is_shootout.

    Extra columns (e.g. player_name from the export) are ignored.
    """
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"gameweek", "player_id", "event_type"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=422,
                            detail=f"CSV must have columns {sorted(required)}.")
    rows, errors = [], []
    for i, rec in enumerate(reader, start=2):
        try:
            rows.append({
                "gameweek": int(rec["gameweek"]),
                "player_id": int(rec["player_id"]),
                "event_type": _parse_event_type(rec["event_type"].strip()),
                "minute": int(rec["minute"]) if rec.get("minute") else None,
                "is_extra_time": str(rec.get("is_extra_time", "0")).strip() in ("1", "true", "True"),
                "is_shootout": str(rec.get("is_shootout", "0")).strip() in ("1", "true", "True"),
            })
        except (ValueError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            errors.append({"line": i, "error": detail})
    if errors:
        return {"ok": False, "dry_run": dry_run, "imported": 0, "errors": errors}

    with SessionFactory() as s:
        pids = {p.id for p in s.scalars(select(Player))}
        gw_by_index = {g.index: g for g in s.scalars(select(Gameweek))}
        svc = _round_service(s)
        imported = 0
        for i, r in enumerate(rows, start=2):
            gw = gw_by_index.get(r["gameweek"])
            if gw is None:
                errors.append({"line": i, "error": f"gameweek {r['gameweek']} not found"})
                continue
            if r["player_id"] not in pids:
                errors.append({"line": i, "error": f"player {r['player_id']} not found"})
                continue
            try:
                svc.add_event(gw.id, r["player_id"], r["event_type"],
                              minute=r["minute"], is_extra_time=r["is_extra_time"],
                              is_shootout=r["is_shootout"])
                imported += 1
            except MatchError as exc:
                errors.append({"line": i, "error": str(exc)})
        if dry_run or errors:
            s.rollback()
        else:
            s.commit()
    return {"ok": not errors, "dry_run": dry_run,
            "imported": imported if not errors else 0,
            "would_import": imported, "errors": errors}


# ---------------------------------------------------------------------------
# Live per-manager valid-goal tally (preview of settlement scoring)
# ---------------------------------------------------------------------------

@router.get("/tally")
def tally(gameweek: int = Query(...)) -> dict:
    with SessionFactory() as s:
        gw = _gw_by_index(s, gameweek)
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        fixtures = s.scalars(select(Fixture).where(Fixture.gameweek_id == gw.id)).all()
        fx_repo = SqlFixtureRepo(s)
        ev_repo = SqlMatchEventRepo(s)
        scorer = ValidGoalCalculator(RULES)

        player_manager = fx_repo.player_manager_map(gw.id)
        all_events = ev_repo.for_players_in_gameweek(gw.id, set(player_manager))

        out = []
        for fx in fixtures:
            home_lu = fx_repo.lineup_for(fx.id, fx.home_manager_id)
            away_lu = fx_repo.lineup_for(fx.id, fx.away_manager_id)
            home = {st["player_id"] for st in (home_lu.starters if home_lu else []) or []}
            away = {st["player_id"] for st in (away_lu.starters if away_lu else []) or []}
            fx_events = [e for e in all_events
                         if e.player_id in home or e.player_id in away]
            score = scorer.score(fx.id, home, away, fx_events)
            out.append({
                "fixture_id": fx.id,
                "group": fx.group_letter, "bracket_slot": fx.bracket_slot,
                "home": names.get(fx.home_manager_id), "away": names.get(fx.away_manager_id),
                "home_goals": score.home_goals, "away_goals": score.away_goals,
                "outcome": score.outcome.value,
                "home_lineup": home_lu is not None, "away_lineup": away_lu is not None,
            })
    return {"gameweek": gameweek, "status": gw.status.value, "fixtures": out}
