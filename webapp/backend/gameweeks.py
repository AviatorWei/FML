"""Gameweek lifecycle — create, set LIVE, finalize (settle pipeline).

Finalize order:
    1. compute FixtureScore per fixture (ValidGoalCalculator, same math the
       engine uses) and persist MatchResult rows with locked_at
    2. RoundService.finalize_gameweek — bonuses, athletics fan-out,
       status → FINALIZED
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from fmlwc.core.enums import GameweekPhase, GameweekStatus
from fmlwc.core.exceptions import MatchError
from fmlwc.domain.match.round import RoundService
from fmlwc.domain.match.scoring import ValidGoalCalculator
from fmlwc.persistence.models.match import (
    BonusAward,
    Fixture,
    Gameweek,
    Lineup,
    MatchEvent,
    MatchResult,
)
from fmlwc.persistence.models.people import Manager
from fmlwc.persistence.sql_repos import (
    SqlAthleticsRepo,
    SqlFixtureRepo,
    SqlGameweekRepo,
    SqlManagerRepo,
    SqlMatchEventRepo,
)

from .deps import RULES, SessionFactory, naive, now_utc, parse_dt, require_admin

router = APIRouter(prefix="/api/admin/gameweeks", tags=["admin:gameweeks"],
                   dependencies=[Depends(require_admin)])


class GameweekCreate(BaseModel):
    index: int
    phase: str  # GROUP | QF | SF | F
    lineup_deadline: str
    competition: str = "LEAGUE"  # LEAGUE | CUP (dual-competition mode)


class FixtureCreate(BaseModel):
    home_manager_id: int
    away_manager_id: int
    group_letter: str | None = None
    bracket_slot: str | None = None


class PkWinner(BaseModel):
    fixture_id: int
    pk_winner_manager_id: int


def _gw_or_404(s, gameweek_id: int) -> Gameweek:
    gw = s.get(Gameweek, gameweek_id)
    if gw is None:
        raise HTTPException(status_code=404, detail=f"Gameweek {gameweek_id} not found.")
    return gw


@router.get("")
def list_gameweeks() -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        total_managers = len(names)
        out = []
        for gw in s.scalars(select(Gameweek).order_by(Gameweek.index)):
            fixtures = s.scalars(select(Fixture).where(Fixture.gameweek_id == gw.id)).all()
            fixture_ids = [f.id for f in fixtures] or [-1]
            lineups = s.scalar(
                select(func.count()).select_from(Lineup)
                .where(Lineup.fixture_id.in_(fixture_ids))) or 0
            events = s.scalar(
                select(func.count()).select_from(MatchEvent)
                .where(MatchEvent.gameweek_id == gw.id)) or 0
            results = s.scalar(
                select(func.count()).select_from(MatchResult)
                .where(MatchResult.fixture_id.in_(fixture_ids))) or 0
            out.append({
                "id": gw.id, "index": gw.index, "phase": gw.phase.value,
                "competition": gw.competition.value,
                "status": gw.status.value,
                "lineup_deadline": gw.lineup_deadline.isoformat() if gw.lineup_deadline else None,
                "fixtures": [
                    {"id": f.id, "home": names.get(f.home_manager_id),
                     "away": names.get(f.away_manager_id),
                     "home_manager_id": f.home_manager_id,
                     "away_manager_id": f.away_manager_id,
                     "group": f.group_letter, "bracket_slot": f.bracket_slot}
                    for f in fixtures
                ],
                "lineups_submitted": lineups,
                "lineups_expected": min(len(fixtures) * 2, total_managers),
                "events": events, "results": results,
            })
    return {"gameweeks": out}


@router.post("")
def create_gameweek(req: GameweekCreate) -> dict:
    from fmlwc.core.enums import Competition

    try:
        phase = GameweekPhase(req.phase)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"Bad phase {req.phase!r} (GROUP/QF/SF/F).")
    try:
        competition = Competition(req.competition)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"Bad competition {req.competition!r} (LEAGUE/CUP).")
    with SessionFactory() as s:
        if s.scalars(select(Gameweek).where(Gameweek.index == req.index)).first():
            raise HTTPException(status_code=409, detail=f"Gameweek {req.index} exists.")
        gw_id = SqlGameweekRepo(s).create(req.index, phase, parse_dt(req.lineup_deadline))
        s.get(Gameweek, gw_id).competition = competition
        s.commit()
        return {"id": gw_id, "index": req.index, "competition": competition.value}


@router.post("/{gameweek_id}/fixtures")
def create_fixture(gameweek_id: int, req: FixtureCreate) -> dict:
    with SessionFactory() as s:
        _gw_or_404(s, gameweek_id)
        for mid in (req.home_manager_id, req.away_manager_id):
            if s.get(Manager, mid) is None:
                raise HTTPException(status_code=404, detail=f"Manager {mid} not found.")
        fid = SqlFixtureRepo(s).create(
            gameweek_id, req.home_manager_id, req.away_manager_id,
            group_letter=req.group_letter, bracket_slot=req.bracket_slot)
        s.commit()
        return {"id": fid}


@router.post("/{gameweek_id}/live")
def set_live(gameweek_id: int) -> dict:
    from .cup import maybe_auto_fork

    at = naive(now_utc())
    with SessionFactory() as s:
        gw = _gw_or_404(s, gameweek_id)
        if gw.status is not GameweekStatus.PENDING:
            raise HTTPException(status_code=409,
                                detail=f"Gameweek is {gw.status.value}, expected PENDING.")
        gw.status = GameweekStatus.LIVE
        s.flush()
        # 第七十七条: the first CUP knockout gameweek going LIVE forks the
        # league/cup rosters into independent games.
        forked = maybe_auto_fork(s, at)
        s.commit()
        return {"ok": True, "status": "LIVE",
                "cup_fork_applied": forked > 0, "cup_entries_created": forked}


@router.post("/{gameweek_id}/pk-winner")
def set_pk_winner(gameweek_id: int, req: PkWinner) -> dict:
    """Record the PK winner on a (drawn) knockout fixture's result row."""
    with SessionFactory() as s:
        _gw_or_404(s, gameweek_id)
        res = s.scalars(
            select(MatchResult).where(MatchResult.fixture_id == req.fixture_id)).first()
        if res is None:
            raise HTTPException(status_code=404,
                                detail="No MatchResult for this fixture yet — finalize first.")
        res.pk_winner_id = req.pk_winner_manager_id
        s.commit()
        return {"ok": True}


def _apply_default_lineups(s, gw, fixtures, at) -> list[int]:
    """Rule 四.8: managers without a lineup get the configured default
    (previous round's lineup, falling back to top market value). Cup-blocked
    players are filtered out of the generated default. Returns manager ids
    that were defaulted."""
    from fmlwc.domain.lineup.defaults import get_default_strategy
    from fmlwc.domain.lineup.validator import StarterInput
    from fmlwc.core.enums import Position
    from .cup import check_starters_cup

    fx_repo = SqlFixtureRepo(s)

    def lineup_loader(manager_id: int, gameweek_index: int):
        prev_gw = s.scalars(
            select(Gameweek).where(Gameweek.index == gameweek_index)).first()
        if prev_gw is None:
            return None
        prev_fx = s.scalars(
            select(Fixture).where(Fixture.gameweek_id == prev_gw.id)
            .where((Fixture.home_manager_id == manager_id)
                   | (Fixture.away_manager_id == manager_id))).first()
        if prev_fx is None:
            return None
        lu = fx_repo.lineup_for(prev_fx.id, manager_id)
        if lu is None:
            return None
        return [StarterInput(player_id=st["player_id"],
                             slot_position=Position(st["slot_position"]))
                for st in (lu.starters or [])]

    from fmlwc.persistence.sql_repos import SqlPlayerRepo

    strategy = get_default_strategy(
        RULES.lineup.default_strategy, RULES,
        SqlPlayerRepo(s), SqlManagerRepo(s), lineup_loader)

    defaulted = []
    for fx in fixtures:
        for manager_id in (fx.home_manager_id, fx.away_manager_id):
            if fx_repo.lineup_for(fx.id, manager_id) is not None:
                continue
            starters = strategy.fill(manager_id, gw.index)
            blocked = {b["player_id"] for b in check_starters_cup(
                s, manager_id, gw.competition, [st.player_id for st in starters])}
            starters = [st for st in starters if st.player_id not in blocked]
            if not starters:
                continue
            fx_repo.save_lineup(
                fx.id, manager_id,
                starters=[{"player_id": st.player_id,
                           "slot_position": st.slot_position.value}
                          for st in starters],
                posted_at=at)
            defaulted.append(manager_id)
    return defaulted


@router.post("/{gameweek_id}/finalize")
def finalize(gameweek_id: int, dry_run: bool = Query(False)) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        gw = _gw_or_404(s, gameweek_id)
        if gw.status is not GameweekStatus.LIVE:
            raise HTTPException(status_code=409,
                                detail=f"Gameweek is {gw.status.value}, expected LIVE.")

        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        fx_repo = SqlFixtureRepo(s)
        ev_repo = SqlMatchEventRepo(s)
        scorer = ValidGoalCalculator(RULES)

        fixtures = s.scalars(select(Fixture).where(Fixture.gameweek_id == gw.id)).all()

        # Rule 四.8 — apply default lineups for managers who didn't submit.
        defaulted = _apply_default_lineups(s, gw, fixtures, at)

        player_manager = fx_repo.player_manager_map(gw.id)
        all_events = ev_repo.for_players_in_gameweek(gw.id, set(player_manager))

        # Reserve teams (预备队, FML 第四十二/四十三条): roster minus starters,
        # league gameweeks only. Pre-compute rosters + reserve events.
        from fmlwc.core.enums import Competition
        from fmlwc.persistence.models.people import RosterEntry
        compute_reserve = gw.competition is Competition.LEAGUE
        roster_by_manager: dict[int, set[int]] = {}
        reserve_events: list = []
        if compute_reserve:
            for e in s.scalars(select(RosterEntry)
                               .where(RosterEntry.released_at.is_(None))):
                roster_by_manager.setdefault(e.manager_id, set()).add(e.player_id)
            reserve_union: set[int] = set()
            for mid, roster_ids in roster_by_manager.items():
                reserve_union |= roster_ids
            reserve_union -= set(player_manager)  # starters excluded
            reserve_events = ev_repo.for_players_in_gameweek(gw.id, reserve_union)
        report_fixtures = []
        for fx in fixtures:
            home_lu = fx_repo.lineup_for(fx.id, fx.home_manager_id)
            away_lu = fx_repo.lineup_for(fx.id, fx.away_manager_id)
            home = {st["player_id"] for st in (home_lu.starters if home_lu else []) or []}
            away = {st["player_id"] for st in (away_lu.starters if away_lu else []) or []}
            fx_events = [e for e in all_events if e.player_id in home or e.player_id in away]
            score = scorer.score(fx.id, home, away, fx_events)

            # Reserve score: rostered non-starters of each side (FML 预备队).
            home_res_goals = away_res_goals = None
            if compute_reserve:
                home_res = roster_by_manager.get(fx.home_manager_id, set()) - home
                away_res = roster_by_manager.get(fx.away_manager_id, set()) - away
                res_events = [e for e in reserve_events
                              if e.player_id in home_res or e.player_id in away_res]
                res_score = scorer.score(fx.id, home_res, away_res, res_events)
                home_res_goals = res_score.home_goals
                away_res_goals = res_score.away_goals

            existing = s.scalars(
                select(MatchResult).where(MatchResult.fixture_id == fx.id)).first()
            if existing is None:
                s.add(MatchResult(fixture_id=fx.id, home_goals=score.home_goals,
                                  away_goals=score.away_goals, outcome=score.outcome,
                                  locked_at=at,
                                  home_reserve_goals=home_res_goals,
                                  away_reserve_goals=away_res_goals))
            else:
                existing.home_goals = score.home_goals
                existing.away_goals = score.away_goals
                existing.outcome = score.outcome
                existing.locked_at = at
                existing.home_reserve_goals = home_res_goals
                existing.away_reserve_goals = away_res_goals
            report_fixtures.append({
                "fixture_id": fx.id,
                "home": names.get(fx.home_manager_id), "away": names.get(fx.away_manager_id),
                "home_goals": score.home_goals, "away_goals": score.away_goals,
                "reserve": ({"home": home_res_goals, "away": away_res_goals}
                            if compute_reserve else None),
                "outcome": score.outcome.value,
                "missing_lineups": [n for n, lu in
                                    ((names.get(fx.home_manager_id), home_lu),
                                     (names.get(fx.away_manager_id), away_lu)) if lu is None],
            })
        s.flush()

        svc = RoundService(
            rules=RULES, gameweeks=SqlGameweekRepo(s), fixtures=fx_repo,
            events=ev_repo, athletics=SqlAthleticsRepo(s), managers=SqlManagerRepo(s))
        try:
            svc.finalize_gameweek(gw.id)
        except NotImplementedError as exc:
            s.rollback()
            raise HTTPException(status_code=501, detail=f"Not implemented: {exc}")
        except MatchError as exc:
            s.rollback()
            raise HTTPException(status_code=409, detail=str(exc))

        bonuses = s.scalars(
            select(BonusAward).where(
                BonusAward.fixture_id.in_([f.id for f in fixtures] or [-1]))).all()
        report = {
            "gameweek": gw.index, "dry_run": dry_run,
            "defaults_applied": [names.get(mid) for mid in defaulted],
            "fixtures": report_fixtures,
            "bonuses": [{"fixture_id": b.fixture_id, "manager": names.get(b.manager_id),
                         "type": b.bonus_type, "amount": b.amount} for b in bonuses],
            "status": "FINALIZED",
        }
        if dry_run:
            s.rollback()
        else:
            s.commit()
        return report
