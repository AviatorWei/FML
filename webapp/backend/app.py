#!/usr/bin/env python3
"""FMLWC web API — a thin FastAPI layer over the existing engine + SQLite DB.

Run from the project root:

    uvicorn webapp.backend.app:app --reload --port 8000

It reuses the domain/IO code already in ``fmlwc``:
  * ``XlsxBidReader``      — parse uploaded sealed-bid xlsx files
  * ``FreeSignService``    — validate & record free-agent signings
  * the SQLAlchemy models  — read managers, players, fixtures, results, stats

The frontend (Vite dev server) proxies ``/api`` here in development.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from .deps import RULES, SessionFactory, naive, now_utc

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fmlwc.core.enums import GameweekStatus
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.transfer.free_sign import FreeSignService
from fmlwc.io.xlsx_bid_reader import XlsxBidParseError, XlsxBidReader
from fmlwc.persistence.models.auction import AuctionResult, AuctionRound
from fmlwc.persistence.models.match import (
    Fixture,
    Gameweek,
    MatchResult,
    PlayerAthletics,
)
from fmlwc.persistence.models.people import Manager, Player, RosterEntry
from fmlwc.persistence.models.transfer import FreeSign, TransferWindow
from fmlwc.persistence.sql_repos import (
    SqlEligibilityRepo,
    SqlFreeSignRepo,
    SqlManagerRepo,
    SqlPlayerRepo,
    SqlTransferRepo,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

app = FastAPI(title="FMLWC API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_naive = naive  # backwards-compat alias for the handlers below

# Routers: exports, auction desk, lineups, events, gameweeks, roster admin, cup.
from . import admin_auction, admin_roster, cup, events, exports, gameweeks, lineups  # noqa: E402

app.include_router(exports.router)
app.include_router(admin_auction.router)
app.include_router(lineups.router)
app.include_router(events.router)
app.include_router(gameweeks.router)
app.include_router(admin_roster.router)
app.include_router(cup.router)

# In dual-competition mode the public league tables only count LEAGUE
# gameweeks and the knockout bracket only counts CUP gameweeks.
from fmlwc.core.enums import Competition  # noqa: E402

_LEAGUE_FILTER = Competition.LEAGUE if RULES.cup.enabled else None
_CUP_FILTER = Competition.CUP if RULES.cup.enabled else None


# ---------------------------------------------------------------------------
# Lightweight serialisers
# ---------------------------------------------------------------------------

def manager_brief(m: Manager) -> dict:
    return {
        "id": m.id,
        "name": m.display_name,
        "manager_name": m.manager_name,
        "group": m.group_letter,
        "balance": m.balance,
        "cup_balance": m.cup_balance,
        "total_points": m.total_points,
    }


def player_dict(p: Player) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "jersey_no": p.jersey_no,
        "position": p.position.value,
        "real_team": p.real_team,
        "market_value": p.market_value,
    }


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/api/time")
def server_time() -> dict:
    n = now_utc()
    return {
        "utc": n.isoformat(),
        "epoch_ms": int(n.timestamp() * 1000),
        "timezone": RULES.scope.timezone,
    }


@app.get("/api/overview")
def overview() -> dict:
    with SessionFactory() as s:
        managers = s.scalar(select(func.count()).select_from(Manager)) or 0
        players = s.scalar(select(func.count()).select_from(Player)) or 0
        rostered = s.scalar(select(func.count()).select_from(RosterEntry)) or 0
        gameweeks = s.scalar(select(func.count()).select_from(Gameweek)) or 0
        results = s.scalar(select(func.count()).select_from(MatchResult)) or 0
        rounds = s.scalar(select(func.count()).select_from(AuctionRound)) or 0
    return {
        "scope": {"name": RULES.scope.name, "short": RULES.scope.short},
        "counts": {
            "managers": managers,
            "players": players,
            "rostered": rostered,
            "gameweeks": gameweeks,
            "results": results,
            "auction_rounds": rounds,
        },
        "rules": {
            "initial_budget": RULES.managers.initial_budget,
            "groups": RULES.managers.groups,
            "min_bid": RULES.auction.min_bid,
            "free_sign_fee": RULES.transfer.free_sign_fee,
        },
    }


# ---------------------------------------------------------------------------
# Standings (league / group / tournament)
# ---------------------------------------------------------------------------

from .standings import compute_standings as _compute_standings  # noqa: E402
from .standings import sort_table as _sort_table  # noqa: E402


@app.get("/api/standings/league")
def standings_league() -> dict:
    with SessionFactory() as s:
        rows = list(_compute_standings(s, _LEAGUE_FILTER).values())
    return {"table": _sort_table(rows)}


@app.get("/api/standings/groups")
def standings_groups() -> dict:
    with SessionFactory() as s:
        rows = list(_compute_standings(s, _LEAGUE_FILTER).values())
    groups: dict[str, list[dict]] = {}
    for r in rows:
        g = r["group"] or "—"
        groups.setdefault(g, []).append(r)
    out = {g: _sort_table(rs) for g, rs in groups.items()}
    return {"groups": dict(sorted(out.items()))}


@app.get("/api/standings/reserve")
def standings_reserve() -> dict:
    """Reserve-team (预备队) league table — FML 第四十三/四十六条.

    Built from the reserve goals stored on finalized LEAGUE results."""
    with SessionFactory() as s:
        managers_all = s.scalars(select(Manager)).all()
        rows = {m.id: {"manager_id": m.id, "name": m.display_name,
                       "group": m.group_letter, "played": 0, "win": 0, "draw": 0,
                       "loss": 0, "gf": 0, "ga": 0, "gd": 0, "points": 0}
                for m in managers_all}
        q = (select(MatchResult, Fixture)
             .join(Fixture, MatchResult.fixture_id == Fixture.id)
             .where(MatchResult.home_reserve_goals.is_not(None)))
        for res, fx in s.execute(q).all():
            h, a = fx.home_manager_id, fx.away_manager_id
            hg, ag = res.home_reserve_goals or 0, res.away_reserve_goals or 0
            if h not in rows or a not in rows:
                continue
            rows[h]["played"] += 1
            rows[a]["played"] += 1
            rows[h]["gf"] += hg
            rows[h]["ga"] += ag
            rows[a]["gf"] += ag
            rows[a]["ga"] += hg
            if hg > ag:
                rows[h]["win"] += 1; rows[a]["loss"] += 1; rows[h]["points"] += 3
            elif ag > hg:
                rows[a]["win"] += 1; rows[h]["loss"] += 1; rows[a]["points"] += 3
            else:
                rows[h]["draw"] += 1; rows[a]["draw"] += 1
                rows[h]["points"] += 1; rows[a]["points"] += 1
        for r in rows.values():
            r["gd"] = r["gf"] - r["ga"]
    return {"table": _sort_table(list(rows.values()))}


@app.get("/api/standings/tournament")
def standings_tournament() -> dict:
    """Knockout bracket. Built from group standings (top 2 per group) per the
    euro2024_8team layout. Match results for knockout fixtures are included
    when present in the DB; otherwise slots show as scheduled/TBD."""
    layout = [
        ("A", 1, "B", 2, "QF1"),
        ("C", 1, "D", 2, "QF2"),
        ("B", 1, "A", 2, "QF3"),
        ("D", 1, "C", 2, "QF4"),
    ]
    with SessionFactory() as s:
        rows = list(_compute_standings(s, _CUP_FILTER or _LEAGUE_FILTER).values())
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r["group"]:
            groups.setdefault(r["group"], []).append(r)
    for g in groups:
        groups[g] = _sort_table(groups[g])

    def seed(letter: str, pos: int) -> Optional[dict]:
        g = groups.get(letter)
        if not g or len(g) < pos:
            return None
        m = g[pos - 1]
        return {"manager_id": m["manager_id"], "name": m["name"], "seed": f"{letter}{pos}"}

    qfs = []
    for hg, hs, ag, as_, slot in layout:
        qfs.append({"slot": slot, "home": seed(hg, hs), "away": seed(ag, as_)})
    return {
        "bracket": RULES.match.knockout.bracket,
        "quarterfinals": qfs,
        "semifinals": [{"slot": "SF1", "home": None, "away": None},
                       {"slot": "SF2", "home": None, "away": None}],
        "final": {"slot": "F", "home": None, "away": None},
        "note": "Semifinal/final pairings populate once knockout results are entered.",
    }


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

@app.get("/api/scores/gameweeks")
def gameweeks() -> dict:
    with SessionFactory() as s:
        gws = s.scalars(select(Gameweek).order_by(Gameweek.index)).all()
        out = [
            {
                "id": gw.id,
                "index": gw.index,
                "phase": gw.phase.value,
                "competition": gw.competition.value,
                "status": gw.status.value,
                "lineup_deadline": gw.lineup_deadline.isoformat()
                if gw.lineup_deadline
                else None,
            }
            for gw in gws
        ]
    return {"gameweeks": out}


def _fixtures_for(s: Session, gw: Gameweek, names: dict[int, str]) -> list[dict]:
    fixtures = s.scalars(
        select(Fixture).where(Fixture.gameweek_id == gw.id).order_by(Fixture.id)
    ).all()
    res_map = {
        r.fixture_id: r
        for r in s.scalars(
            select(MatchResult).where(
                MatchResult.fixture_id.in_([f.id for f in fixtures] or [-1])
            )
        ).all()
    }
    out = []
    for f in fixtures:
        r = res_map.get(f.id)
        out.append(
            {
                "fixture_id": f.id,
                "group": f.group_letter,
                "bracket_slot": f.bracket_slot,
                "home": {"id": f.home_manager_id, "name": names.get(f.home_manager_id)},
                "away": {"id": f.away_manager_id, "name": names.get(f.away_manager_id)},
                "home_goals": r.home_goals if r else None,
                "away_goals": r.away_goals if r else None,
                "outcome": r.outcome.value if r else None,
                "played": r is not None,
                "final": bool(r and r.locked_at),
            }
        )
    return out


@app.get("/api/scores")
def scores(
    status: str = Query("all", pattern="^(all|live|finalized|pending)$"),
    gameweek: Optional[int] = None,
) -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager)).all()}
        stmt = select(Gameweek).order_by(Gameweek.index)
        gws = s.scalars(stmt).all()
        if gameweek is not None:
            gws = [g for g in gws if g.index == gameweek]
        if status == "live":
            gws = [g for g in gws if g.status is GameweekStatus.LIVE]
        elif status == "finalized":
            gws = [g for g in gws if g.status is GameweekStatus.FINALIZED]
        elif status == "pending":
            gws = [g for g in gws if g.status is GameweekStatus.PENDING]

        out = [
            {
                "id": gw.id,
                "index": gw.index,
                "phase": gw.phase.value,
                "competition": gw.competition.value,
                "status": gw.status.value,
                "fixtures": _fixtures_for(s, gw, names),
            }
            for gw in gws
        ]
    return {"gameweeks": out}


# ---------------------------------------------------------------------------
# Player scoreboard
# ---------------------------------------------------------------------------

def _pk_points(a: PlayerAthletics) -> float:
    cfg = RULES.match.knockout.pk_score
    return round(
        a.goals * cfg.goal
        + a.assists * cfg.assist
        + a.yellows * cfg.yellow
        + a.second_yellow_reds * cfg.second_yellow_red
        + a.reds * cfg.red,
        2,
    )


@app.get("/api/players")
def players(
    q: Optional[str] = None,
    position: Optional[str] = Query(None, pattern="^(G|D|M|W|F)$"),
    sort: str = Query("goals", pattern="^(goals|assists|points|value|name)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with SessionFactory() as s:
        ath = {a.player_id: a for a in s.scalars(select(PlayerAthletics)).all()}
        owner_by_player: dict[int, str] = {}
        price_by_player: dict[int, int] = {}
        rows = s.execute(
            select(RosterEntry, Manager.display_name)
            .join(Manager, RosterEntry.manager_id == Manager.id)
            .where(RosterEntry.released_at.is_(None))
        ).all()
        for entry, mgr_name in rows:
            owner_by_player[entry.player_id] = mgr_name
            price_by_player[entry.player_id] = entry.acquired_price

        stmt = select(Player)
        if q:
            stmt = stmt.where(Player.name.ilike(f"%{q}%"))
        if position:
            stmt = stmt.where(Player.position == position)
        all_players = s.scalars(stmt).all()

        out = []
        for p in all_players:
            a = ath.get(p.id)
            goals = a.goals if a else 0
            assists = a.assists if a else 0
            yellows = a.yellows if a else 0
            reds = a.reds if a else 0
            saved_pens = a.saved_penalties if a else 0
            pk = _pk_points(a) if a else 0.0
            # fantasy points: simple, transparent scoring line
            fpts = round(goals * 5 + assists * 3 + saved_pens * 5 - yellows - reds * 3, 1)
            out.append(
                {
                    **player_dict(p),
                    "owner": owner_by_player.get(p.id),
                    "acquired_price": price_by_player.get(p.id),
                    "goals": goals,
                    "assists": assists,
                    "yellows": yellows,
                    "reds": reds,
                    "saved_penalties": saved_pens,
                    "pk_points": pk,
                    "fantasy_points": fpts,
                }
            )

    keymap = {
        "goals": lambda r: (-r["goals"], -r["assists"], r["name"]),
        "assists": lambda r: (-r["assists"], -r["goals"], r["name"]),
        "points": lambda r: (-r["fantasy_points"], r["name"]),
        "value": lambda r: (-(r["market_value"] or 0), r["name"]),
        "name": lambda r: (r["name"],),
    }
    out.sort(key=keymap[sort])
    total = len(out)
    page = out[offset : offset + limit]
    for i, r in enumerate(page, start=offset + 1):
        r["rank"] = i
    return {"total": total, "count": len(page), "players": page}


@app.get("/api/players/search")
def player_search(q: str = Query(..., min_length=1), limit: int = Query(15, ge=1, le=50)) -> dict:
    """Lookup used by the free-sign page: returns identity + auto-formatted
    position/club and whether the player is currently a free agent."""
    at = now_utc()
    with SessionFactory() as s:
        plr_repo = SqlPlayerRepo(s)
        stmt = select(Player)
        if q.isdigit():
            stmt = stmt.where(Player.id == int(q))
        else:
            stmt = stmt.where(Player.name.ilike(f"%{q}%"))
        found = s.scalars(stmt.limit(limit)).all()
        owner_rows = {
            e.player_id: name
            for e, name in s.execute(
                select(RosterEntry, Manager.display_name)
                .join(Manager, RosterEntry.manager_id == Manager.id)
                .where(RosterEntry.released_at.is_(None))
            ).all()
        }
        out = []
        for p in found:
            try:
                free = plr_repo.is_free_agent(p.id, at)
            except Exception:
                free = p.id not in owner_rows
            out.append(
                {
                    **player_dict(p),
                    "owner": owner_rows.get(p.id),
                    "free_agent": free,
                }
            )
    return {"players": out}


# ---------------------------------------------------------------------------
# Auction results
# ---------------------------------------------------------------------------

@app.get("/api/auction/results")
def auction_results(round_index: Optional[int] = None) -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager)).all()}
        players_by_id = {p.id: p for p in s.scalars(select(Player)).all()}
        rounds = s.scalars(select(AuctionRound).order_by(AuctionRound.index)).all()
        out = []
        for rnd in rounds:
            if round_index is not None and rnd.index != round_index:
                continue
            results = s.scalars(
                select(AuctionResult).where(AuctionResult.round_id == rnd.id)
            ).all()
            items = []
            for r in results:
                p = players_by_id.get(r.player_id)
                items.append(
                    {
                        "player_id": r.player_id,
                        "player_name": p.name if p else None,
                        "position": p.position.value if p else None,
                        "real_team": p.real_team if p else None,
                        "winner": names.get(r.winner_manager_id),
                        "price": r.price,
                    }
                )
            items.sort(key=lambda x: -x["price"])
            out.append(
                {
                    "round_index": rnd.index,
                    "status": rnd.status.value,
                    "awards": len(items),
                    "total_spend": sum(i["price"] for i in items),
                    "items": items,
                }
            )
    return {"rounds": out}


# ---------------------------------------------------------------------------
# Bid upload + parse
# ---------------------------------------------------------------------------

@app.post("/api/bids/upload")
async def upload_bids(file: UploadFile = File(...)) -> dict:
    """Parse an uploaded sealed-bid xlsx (FME_<year>_Bid<N>_<CODE>.xlsx).

    Returns the parsed bids. Parsing only — no DB writes — so it is safe to
    use as a pre-submission validator."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload a .xlsx bid file.")

    data = await file.read()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / file.filename
        tmp_path.write_bytes(data)
        reader = XlsxBidReader(tmp)
        try:
            sub = reader.read_file(file.filename)
        except XlsxBidParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    bids = [
        {
            "rank_in_position": r.rank_in_position,
            "amount": r.amount,
            "player_id": r.player_id,
            "player_name": r.player_name,
            "real_team": r.real_team,
            "position": r.position_str,
        }
        for r in sub.rows
    ]
    # resolve manager by code for convenience
    with SessionFactory() as s:
        mgr = s.scalars(
            select(Manager).where(Manager.display_name == sub.manager_code)
        ).first()
    return {
        "source_file": sub.source_file,
        "manager_code": sub.manager_code,
        "manager_id": mgr.id if mgr else None,
        "round_index": sub.round_index,
        "bid_count": len(bids),
        "total_amount": sum(b["amount"] for b in bids),
        "min_bid_rule": RULES.auction.min_bid,
        "bids": bids,
    }


# ---------------------------------------------------------------------------
# Transfer windows + free signing
# ---------------------------------------------------------------------------

@app.get("/api/transfer/windows")
def transfer_windows() -> dict:
    at = _naive(now_utc())
    with SessionFactory() as s:
        windows = s.scalars(select(TransferWindow).order_by(TransferWindow.opens_at)).all()
        out = []
        active = None
        for w in windows:
            is_open = w.opens_at <= at <= w.closes_at
            row = {
                "id": w.id,
                "opens_at": w.opens_at.isoformat(),
                "closes_at": w.closes_at.isoformat(),
                "free_sign_period_seconds": w.free_sign_period_seconds,
                "status": w.status.value,
                "is_open_now": is_open,
            }
            if is_open:
                active = row
            out.append(row)
    return {
        "server_utc": now_utc().isoformat(),
        "active_window": active,
        "free_sign_fee": RULES.transfer.free_sign_fee,
        "revoke_window_seconds": RULES.transfer.revoke_window_seconds,
        "windows": out,
    }


@app.get("/api/managers")
def managers() -> dict:
    with SessionFactory() as s:
        ms = s.scalars(select(Manager).order_by(Manager.display_name)).all()
        out = []
        for m in ms:
            roster_n = s.scalar(
                select(func.count())
                .select_from(RosterEntry)
                .where(RosterEntry.manager_id == m.id, RosterEntry.released_at.is_(None))
            )
            out.append({**manager_brief(m), "roster_size": roster_n or 0})
    return {"managers": out}


class FreeSignRequest(BaseModel):
    manager_id: int
    player_id: int


def _build_free_sign_service(session: Session) -> FreeSignService:
    mgr_repo = SqlManagerRepo(session)
    plr_repo = SqlPlayerRepo(session)
    trn_repo = SqlTransferRepo(session)
    fs_repo = SqlFreeSignRepo(session)
    elig_repo = SqlEligibilityRepo(session)
    elig_svc = EligibilityService(RULES, mgr_repo, plr_repo, elig_repo)
    return FreeSignService(
        rules=RULES,
        managers=mgr_repo,
        players=plr_repo,
        transfers=trn_repo,
        free_signs=fs_repo,
        eligibility=elig_svc,
    )


@app.post("/api/free-sign")
def free_sign(req: FreeSignRequest) -> dict:
    """Propose a free signing. The backend stamps the server time and runs the
    real ``FreeSignService`` validation against the configured transfer window."""
    posted_at = now_utc()
    with SessionFactory() as s:
        mgr = s.get(Manager, req.manager_id)
        plr = s.get(Player, req.player_id)
        if mgr is None:
            raise HTTPException(status_code=404, detail="Manager not found.")
        if plr is None:
            raise HTTPException(status_code=404, detail="Player not found.")
        svc = _build_free_sign_service(s)
        result = svc.try_propose(req.manager_id, req.player_id, posted_at)
        if not result.success:
            s.rollback()
            return {
                "success": False,
                "error": result.error,
                "posted_at": posted_at.isoformat(),
            }
        s.commit()
        return {
            "success": True,
            "free_sign_id": result.free_sign_id,
            "manager": mgr.display_name,
            "player": plr.name,
            "fee": RULES.transfer.free_sign_fee,
            "posted_at": posted_at.isoformat(),
            "revoke_window_seconds": RULES.transfer.revoke_window_seconds,
        }


@app.get("/api/free-sign/list")
def free_sign_list() -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager)).all()}
        pnames = {p.id: p.name for p in s.scalars(select(Player)).all()}
        rows = s.scalars(select(FreeSign).order_by(FreeSign.posted_at.desc())).all()
        out = [
            {
                "id": fs.id,
                "manager": names.get(fs.manager_id),
                "player": pnames.get(fs.player_id),
                "fee": fs.fee,
                "posted_at": fs.posted_at.isoformat(),
                "revoked": fs.revoked,
                "effective": fs.effective,
            }
            for fs in rows
        ]
    return {"free_signs": out}


@app.post("/api/free-sign/{free_sign_id}/revoke")
def free_sign_revoke(free_sign_id: int) -> dict:
    """Revoke a pending free sign within the revoke window (rule 三.5)."""
    at = now_utc()
    with SessionFactory() as s:
        svc = _build_free_sign_service(s)
        result = svc.try_revoke(free_sign_id, at)
        if not result.success:
            s.rollback()
            return {"success": False, "error": result.error}
        s.commit()
        return {"success": True, "free_sign_id": free_sign_id}


@app.post("/api/free-sign/commit-due")
def free_sign_commit_due() -> dict:
    """Commit all pending free signs whose revoke window has elapsed.

    Idempotent; safe to call from a cron or the admin UI."""
    at = now_utc()
    with SessionFactory() as s:
        svc = _build_free_sign_service(s)
        committed = svc.commit_due(at)
        s.commit()
        return {"committed": committed}


# ---------------------------------------------------------------------------
# Releases (rule 八) — pending → revoke window → effective
# ---------------------------------------------------------------------------

class ReleaseRequest(BaseModel):
    manager_id: int
    player_id: int


def _build_release_service(session: Session):
    from fmlwc.domain.transfer.release import ReleaseService
    from fmlwc.persistence.sql_repos import SqlReleaseRepo

    mgr_repo = SqlManagerRepo(session)
    plr_repo = SqlPlayerRepo(session)
    elig_svc = EligibilityService(RULES, mgr_repo, plr_repo, SqlEligibilityRepo(session))
    return ReleaseService(rules=RULES, managers=mgr_repo, eligibility=elig_svc,
                          releases=SqlReleaseRepo(session))


@app.post("/api/releases")
def release_propose(req: ReleaseRequest) -> dict:
    posted_at = now_utc()
    with SessionFactory() as s:
        svc = _build_release_service(s)
        ok, release_id, error = svc.try_propose(req.manager_id, req.player_id, posted_at)
        if not ok:
            s.rollback()
            return {"success": False, "error": error}
        s.commit()
        return {"success": True, "release_id": release_id,
                "posted_at": posted_at.isoformat(),
                "revoke_window_seconds": RULES.release.revoke_window_seconds}


@app.post("/api/releases/{release_id}/revoke")
def release_revoke(release_id: int) -> dict:
    with SessionFactory() as s:
        svc = _build_release_service(s)
        ok, _, error = svc.try_revoke(release_id, now_utc())
        if not ok:
            s.rollback()
            return {"success": False, "error": error}
        s.commit()
        return {"success": True}


@app.post("/api/releases/commit-due")
def release_commit_due() -> dict:
    """Commit pending releases past the revoke window (idempotent)."""
    with SessionFactory() as s:
        committed = _build_release_service(s).commit_due(now_utc())
        s.commit()
        return {"committed": committed}


@app.get("/api/releases/list")
def release_list() -> dict:
    from fmlwc.persistence.models.transfer import Release

    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager)).all()}
        pnames = {p.id: p.name for p in s.scalars(select(Player)).all()}
        rows = s.scalars(select(Release).order_by(Release.posted_at.desc())).all()
        out = [
            {"id": r.id, "manager": names.get(r.manager_id),
             "player": pnames.get(r.player_id),
             "posted_at": r.posted_at.isoformat(),
             "revoked": r.revoked, "effective": r.effective}
            for r in rows
        ]
    return {"releases": out}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
