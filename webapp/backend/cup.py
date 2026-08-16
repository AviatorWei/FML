"""Dual-competition (league + cup) API — fork model per FMC 第七十七/七十八条.

* Before separation: the cup list (FMC大名单) is a derived view — every
  owned player whose real team plays the cup. Operations are shared.
* POST /api/cup/separate (or the first CUP knockout gameweek going LIVE)
  forks the cup list into ``cup_roster_entries``; from then on league and
  cup operations are independent.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from fmlwc.core.enums import Competition, GameweekPhase, GameweekStatus
from fmlwc.domain.competition import CupEligibilityService
from fmlwc.persistence.models.competition import CupRosterEntry, CupState
from fmlwc.persistence.models.match import Gameweek
from fmlwc.persistence.models.people import Manager, Player, RosterEntry

from .deps import RULES, SessionFactory, naive, now_utc, require_admin

router = APIRouter(prefix="/api/cup", tags=["cup"])

CUP_SVC = CupEligibilityService(RULES)


# ---------------------------------------------------------------------------
# Shared helpers (imported by lineups.py / gameweeks.py / admin_roster.py)
# ---------------------------------------------------------------------------

def cup_knockout_started(s) -> bool:
    """True once any CUP knockout gameweek has gone LIVE (or beyond)."""
    row = s.scalars(
        select(Gameweek)
        .where(Gameweek.competition == Competition.CUP)
        .where(Gameweek.phase != GameweekPhase.GROUP)
        .where(Gameweek.status != GameweekStatus.PENDING)
    ).first()
    return row is not None


def get_cup_state(s) -> CupState:
    state = s.scalars(select(CupState)).first()
    if state is None:
        state = CupState(separated_at=None)
        s.add(state)
        s.flush()
    return state


def separation_active(s) -> bool:
    return get_cup_state(s).separated_at is not None


def cup_roster_player_ids(s, manager_id: int) -> set[int]:
    """The manager's current cup list (FMC大名单) as player ids.

    Derived (linked) before separation; authoritative table afterwards."""
    if separation_active(s):
        return {
            e.player_id for e in s.scalars(
                select(CupRosterEntry)
                .where(CupRosterEntry.manager_id == manager_id)
                .where(CupRosterEntry.released_at.is_(None)))
        }
    players = {p.id: p for p in s.scalars(select(Player))}
    return {
        e.player_id for e in s.scalars(
            select(RosterEntry)
            .where(RosterEntry.manager_id == manager_id)
            .where(RosterEntry.released_at.is_(None)))
        if (p := players.get(e.player_id)) is not None
        and CUP_SVC.is_cup_team(p.real_team)
    }


def check_starters_cup(
    s, manager_id: int, competition: Competition, player_ids: list[int]
) -> list[dict]:
    """Return [{player_id, player, reason}] for starters blocked by cup rules."""
    if not CUP_SVC.enabled:
        return []
    separated = separation_active(s)
    cup_ids = (cup_roster_player_ids(s, manager_id)
               if (separated and competition is Competition.CUP) else set())
    players = {p.id: p for p in s.scalars(
        select(Player).where(Player.id.in_(player_ids or [-1])))}
    blocked = []
    for pid in player_ids:
        p = players.get(pid)
        if p is None:
            continue
        verdict = CUP_SVC.check_starter(
            p.real_team, competition,
            separated=separated,
            on_cup_roster=(pid in cup_ids) if separated else True)
        if not verdict.allowed:
            blocked.append({"player_id": pid, "player": p.name, "reason": verdict.reason})
    return blocked


def run_fork(s, at: datetime) -> int:
    """Copy every owned cup-eligible player into cup_roster_entries.

    Idempotent: does nothing if already separated. Returns rows created."""
    state = get_cup_state(s)
    if state.separated_at is not None:
        return 0
    players = {p.id: p for p in s.scalars(select(Player))}
    created = 0
    for e in s.scalars(select(RosterEntry).where(RosterEntry.released_at.is_(None))):
        p = players.get(e.player_id)
        if p is None or not CUP_SVC.is_cup_team(p.real_team):
            continue
        s.add(CupRosterEntry(
            manager_id=e.manager_id, player_id=e.player_id,
            acquired_at=e.acquired_at, acquired_via=e.acquired_via,
            acquired_price=e.acquired_price))
        created += 1
    state.separated_at = at
    s.flush()
    return created


def maybe_auto_fork(s, at: datetime) -> int:
    """Fork automatically once the cup knockout has started (rule-driven)."""
    if CUP_SVC.separation_due(cup_knockout_started(s)) and not separation_active(s):
        return run_fork(s, at)
    return 0


# ---------------------------------------------------------------------------
# Status + cup roster view
# ---------------------------------------------------------------------------

@router.get("/status")
def status() -> dict:
    with SessionFactory() as s:
        state = get_cup_state(s)
        started = cup_knockout_started(s)
        s.commit()  # persist lazily-created CupState row
    return {
        "enabled": CUP_SVC.enabled,
        "extra_teams": list(RULES.cup.extra_teams),
        "league_teams_in_cup": list(RULES.cup.league_teams_in_cup),
        "separate_after_group": RULES.cup.separate_after_group,
        "cup_knockout_started": started,
        "separation_active": state.separated_at is not None,
        "separated_at": state.separated_at.isoformat() if state.separated_at else None,
        "note": ("Group stage: one shared roster — dual players float between "
                 "league and cup, operations affect both. Knockout: rosters "
                 "fork and the games become independent (第七十七条)."),
    }


@router.get("/roster")
def cup_roster(manager_id: int | None = None) -> dict:
    """The FMC大名单 per manager (derived pre-fork, forked table after)."""
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        players = {p.id: p for p in s.scalars(select(Player))}
        separated = separation_active(s)
        out = []
        manager_ids = ([manager_id] if manager_id is not None
                       else sorted(names))
        for mid in manager_ids:
            for pid in sorted(cup_roster_player_ids(s, mid)):
                p = players.get(pid)
                if p is None:
                    continue
                out.append({
                    "manager_id": mid, "manager": names.get(mid),
                    "player_id": pid, "player": p.name,
                    "position": p.position.value, "real_team": p.real_team,
                    "kind": CUP_SVC.classify(p.real_team),
                })
    return {"separated": separated, "entries": out}


# ---------------------------------------------------------------------------
# Separation (fork)
# ---------------------------------------------------------------------------

@router.post("/separate", dependencies=[Depends(require_admin)])
def separate() -> dict:
    """Manually trigger the league/cup fork (idempotent). Normally happens
    automatically when the first CUP knockout gameweek goes LIVE."""
    if not CUP_SVC.enabled:
        raise HTTPException(status_code=409, detail="Cup mode is disabled.")
    at = naive(now_utc())
    with SessionFactory() as s:
        if separation_active(s):
            return {"ok": True, "already_separated": True, "created": 0}
        created = run_fork(s, at)
        s.commit()
        return {"ok": True, "already_separated": False, "created": created,
                "separated_at": at.isoformat()}
