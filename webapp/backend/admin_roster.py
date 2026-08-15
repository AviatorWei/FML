"""Roster + transfer administration.

Uses implemented engine services where they exist (``DismissService``,
``EligibilityService``); backs the still-stubbed release/trade/pick services
with direct, checked ORM logic so the flows work end-to-end today. When those
services land, swap the bodies to call them.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from fmlwc.core.enums import (
    AcquisitionVia,
    EligibilityRestriction,
    Position,
)
from fmlwc.core.exceptions import EligibilityError, MatchError, TransferError
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.match.pick import PickService
from fmlwc.domain.transfer.dismiss import DismissService
from fmlwc.domain.transfer.trade import TradeLegInput, TradeService
from fmlwc.persistence.models.injury import InjuryAdjustment
from fmlwc.persistence.models.match import Fixture
from fmlwc.persistence.models.people import Manager, Player, RosterEntry
from fmlwc.persistence.models.transfer import Release, Trade, TradeLeg, TransferWindow
from fmlwc.persistence.sql_repos import (
    SqlDismissalRepo,
    SqlEligibilityRepo,
    SqlManagerRepo,
    SqlPickRepo,
    SqlPlayerRepo,
    SqlSnapshotRepo,
    SqlTradeRepo,
    SqlTransferRepo,
)

from .deps import RULES, SessionFactory, naive, now_utc, parse_dt, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin:roster"],
                   dependencies=[Depends(require_admin)])


def _eligibility(s) -> EligibilityService:
    return EligibilityService(RULES, SqlManagerRepo(s), SqlPlayerRepo(s),
                              SqlEligibilityRepo(s))


def _mgr_or_404(s, manager_id: int) -> Manager:
    m = s.get(Manager, manager_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Manager {manager_id} not found.")
    return m


def _plr_or_404(s, player_id: int) -> Player:
    p = s.get(Player, player_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")
    return p


# ---------------------------------------------------------------------------
# Roster list / add / release
# ---------------------------------------------------------------------------

@router.get("/roster")
def roster(manager_id: int | None = None, include_released: bool = False) -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        players = {p.id: p for p in s.scalars(select(Player))}
        stmt = select(RosterEntry).order_by(RosterEntry.manager_id, RosterEntry.id)
        if manager_id is not None:
            stmt = stmt.where(RosterEntry.manager_id == manager_id)
        if not include_released:
            stmt = stmt.where(RosterEntry.released_at.is_(None))
        out = []
        for e in s.scalars(stmt):
            p = players.get(e.player_id)
            out.append({
                "id": e.id, "manager_id": e.manager_id, "manager": names.get(e.manager_id),
                "player_id": e.player_id, "player": p.name if p else None,
                "position": p.position.value if p else None,
                "real_team": p.real_team if p else None,
                "via": e.acquired_via.value, "price": e.acquired_price,
                "acquired_at": e.acquired_at.isoformat(),
                "released_at": e.released_at.isoformat() if e.released_at else None,
            })
    return {"entries": out}


class RosterAdd(BaseModel):
    manager_id: int
    player_id: int
    via: str = "AUCTION"
    price: int = 0
    charge_balance: bool = True


@router.post("/roster")
def roster_add(req: RosterAdd) -> dict:
    """Add a free agent to a roster.

    Dual-competition mode wallet routing (FMC 第十三/七十八条): players from
    cup-exclusive teams are paid from the manager's cup wallet; during the
    cup group stage the cup wallet can ONLY pay for such players. League
    players always use the league wallet."""
    from .cup import CUP_SVC, separation_active

    at = naive(now_utc())
    try:
        via = AcquisitionVia(req.via)
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"Bad via {req.via!r}: "
                                   + ", ".join(v.value for v in AcquisitionVia))
    with SessionFactory() as s:
        mgr = _mgr_or_404(s, req.manager_id)
        player = _plr_or_404(s, req.player_id)
        mgr_repo = SqlManagerRepo(s)
        if not SqlPlayerRepo(s).is_free_agent(req.player_id, at):
            raise HTTPException(status_code=409, detail="Player is not a free agent.")
        verdict = _eligibility(s).check(req.manager_id, req.player_id, via,
                                        fee=req.price, at=at)
        if not verdict.allowed:
            raise HTTPException(status_code=422, detail=f"Eligibility: {verdict.reason}")

        use_cup_wallet = CUP_SVC.enabled and CUP_SVC.is_cup_only_team(player.real_team)
        if req.charge_balance and req.price:
            if use_cup_wallet:
                spend = CUP_SVC.check_cup_spend(player.real_team,
                                                separated=separation_active(s))
                if not spend.allowed:
                    raise HTTPException(status_code=422, detail=spend.reason)
                if mgr.cup_balance < req.price:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Insufficient cup balance ({mgr.cup_balance} < {req.price}).")
                mgr.cup_balance -= req.price
            else:
                if mgr.balance < req.price:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Insufficient balance ({mgr.balance} < {req.price}).")
                mgr_repo.adjust_balance(req.manager_id, -req.price,
                                        reason=f"admin roster add player {req.player_id}")
        mgr_repo.add_to_roster(req.manager_id, req.player_id,
                               acquired_at=at, via=via, price=req.price)
        s.commit()
        return {"ok": True, "wallet": "cup" if use_cup_wallet else "league"}


class RosterRelease(BaseModel):
    manager_id: int
    player_id: int
    lifetime_block: bool = True
    competition: str = "LEAGUE"  # post-fork: LEAGUE or CUP (第七十七条)


@router.post("/roster/release")
def roster_release(req: RosterRelease) -> dict:
    """Immediate admin release. Records a Release audit row and — per rule
    八.4 — a RELEASED_LIFETIME eligibility block for the releasing manager.

    Dual-competition mode: before separation a release affects both games
    (shared roster). After separation, pass ``competition`` to target the
    league roster or the independent cup list."""
    from fmlwc.persistence.models.competition import CupRosterEntry
    from .cup import separation_active

    at = naive(now_utc())
    with SessionFactory() as s:
        _mgr_or_404(s, req.manager_id)
        _plr_or_404(s, req.player_id)
        if req.competition == "CUP" and separation_active(s):
            entry = s.scalars(
                select(CupRosterEntry)
                .where(CupRosterEntry.manager_id == req.manager_id)
                .where(CupRosterEntry.player_id == req.player_id)
                .where(CupRosterEntry.released_at.is_(None))).first()
            if entry is None:
                raise HTTPException(status_code=409,
                                    detail="Player not on the manager's cup roster.")
            entry.released_at = at
        else:
            try:
                SqlManagerRepo(s).release_from_roster(req.manager_id, req.player_id, at)
            except KeyError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
        s.add(Release(manager_id=req.manager_id, player_id=req.player_id,
                      posted_at=at, revoked=False, effective=True))
        if req.lifetime_block:
            SqlEligibilityRepo(s).add(
                req.manager_id, req.player_id,
                EligibilityRestriction.RELEASED_LIFETIME, None,
                reason=f"voluntary release ({req.competition}, rule 八.4/第六十条)")
        s.commit()
        return {"ok": True, "competition": req.competition}


# ---------------------------------------------------------------------------
# Bulk roster import (round-trips with /api/export/rosters.csv)
# ---------------------------------------------------------------------------

@router.post("/roster/import")
async def roster_import(file: UploadFile = File(...), dry_run: bool = Query(True)) -> dict:
    """CSV columns: Manager, PlayerID, Via, Price (extra columns ignored).

    Adds each player to the named manager's roster if they're currently a
    free agent; rows for already-owned players are reported as skipped."""
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    need = {"Manager", "PlayerID"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=422, detail=f"CSV must have columns {sorted(need)}.")
    at = naive(now_utc())
    added, skipped, errors = 0, [], []
    with SessionFactory() as s:
        by_code = {m.display_name: m for m in s.scalars(select(Manager))}
        pids = {p.id for p in s.scalars(select(Player))}
        mgr_repo, plr_repo = SqlManagerRepo(s), SqlPlayerRepo(s)
        for i, rec in enumerate(reader, start=2):
            mgr = by_code.get((rec.get("Manager") or "").strip())
            if mgr is None:
                errors.append({"line": i, "error": f"manager {rec.get('Manager')!r} not found"})
                continue
            try:
                pid = int(rec["PlayerID"])
                price = int(rec.get("Price") or 0)
                via = AcquisitionVia((rec.get("Via") or "AUCTION").strip())
            except (ValueError, KeyError) as exc:
                errors.append({"line": i, "error": str(exc)})
                continue
            if pid not in pids:
                errors.append({"line": i, "error": f"player {pid} not found"})
                continue
            if not plr_repo.is_free_agent(pid, at):
                skipped.append({"line": i, "player_id": pid, "reason": "already owned"})
                continue
            mgr_repo.add_to_roster(mgr.id, pid, acquired_at=at, via=via, price=price)
            added += 1
        if dry_run or errors:
            s.rollback()
        else:
            s.commit()
    return {"ok": not errors, "dry_run": dry_run,
            "added": added if not (dry_run or errors) else 0,
            "would_add": added, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Dismissal (implemented engine service)
# ---------------------------------------------------------------------------

class DismissalIn(BaseModel):
    manager_id: int
    player_id: int
    reason: str | None = None


@router.post("/dismissals")
def dismiss(req: DismissalIn) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        _mgr_or_404(s, req.manager_id)
        _plr_or_404(s, req.player_id)
        svc = DismissService(RULES, SqlManagerRepo(s), SqlDismissalRepo(s), _eligibility(s))
        try:
            dismissal_id = svc.dismiss(req.manager_id, req.player_id, at, reason=req.reason)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        s.commit()
        return {"ok": True, "dismissal_id": dismissal_id}


# ---------------------------------------------------------------------------
# Injury adjustment (service is a stub — direct implementation)
# ---------------------------------------------------------------------------

class InjuryIn(BaseModel):
    player_id: int
    refund_amount: int | None = None  # default: acquired price
    free_sign_grant: bool = False
    granted_to_manager_id: int | None = None


@router.post("/injuries")
def injury(req: InjuryIn) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        _plr_or_404(s, req.player_id)
        entry = s.scalars(
            select(RosterEntry).where(RosterEntry.player_id == req.player_id)
            .where(RosterEntry.released_at.is_(None))).first()
        owner_id, refund = None, 0
        if entry is not None:
            owner_id = entry.manager_id
            refund = req.refund_amount if req.refund_amount is not None else entry.acquired_price
            SqlManagerRepo(s).release_from_roster(owner_id, req.player_id, at)
            if refund:
                SqlManagerRepo(s).adjust_balance(owner_id, refund,
                                                 reason=f"injury refund player {req.player_id}")
        grant_to = req.granted_to_manager_id or owner_id
        s.add(InjuryAdjustment(
            real_player_id=req.player_id, removed_at=at, refund_amount=refund,
            free_sign_grant=req.free_sign_grant,
            granted_to_manager_id=grant_to if req.free_sign_grant else None))
        s.commit()
        return {"ok": True, "owner_released": owner_id is not None,
                "refund": refund, "free_sign_grant": req.free_sign_grant}


# ---------------------------------------------------------------------------
# Trades (service is a stub — direct implementation with checks)
# ---------------------------------------------------------------------------

class TradeLegIn(BaseModel):
    side: str  # INITIATOR | COUNTERPARTY
    player_id: int | None = None
    cash_amount: int | None = None


class TradeIn(BaseModel):
    initiator_id: int
    counterparty_id: int
    legs: list[TradeLegIn]


@router.get("/trades")
def list_trades() -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        pnames = {p.id: p.name for p in s.scalars(select(Player))}
        legs_by_trade: dict[int, list[dict]] = {}
        for leg in s.scalars(select(TradeLeg)):
            legs_by_trade.setdefault(leg.trade_id, []).append({
                "side": leg.side.value, "player_id": leg.player_id,
                "player": pnames.get(leg.player_id) if leg.player_id else None,
                "cash_amount": leg.cash_amount})
        out = [{
            "id": t.id, "initiator": names.get(t.initiator_id),
            "counterparty": names.get(t.counterparty_id),
            "initiator_id": t.initiator_id, "counterparty_id": t.counterparty_id,
            "status": t.status.value, "legs": legs_by_trade.get(t.id, []),
            "proposed_at": t.proposed_at.isoformat(),
            "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        } for t in s.scalars(select(Trade).order_by(Trade.proposed_at.desc()))]
    return {"trades": out}


def _trade_service(s) -> TradeService:
    return TradeService(
        rules=RULES, managers=SqlManagerRepo(s), players=SqlPlayerRepo(s),
        eligibility=_eligibility(s), trades=SqlTradeRepo(s),
        transfers=SqlTransferRepo(s))


@router.post("/trades")
def propose_trade(req: TradeIn) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        _mgr_or_404(s, req.initiator_id)
        _mgr_or_404(s, req.counterparty_id)
        svc = _trade_service(s)
        try:
            trade_id = svc.propose(
                req.initiator_id, req.counterparty_id,
                [TradeLegInput(side=l.side, player_id=l.player_id,
                               cash_amount=l.cash_amount) for l in req.legs],
                at)
        except TransferError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        s.commit()
        return {"ok": True, "trade_id": trade_id}


@router.post("/trades/{trade_id}/{action}")
def resolve_trade(trade_id: int, action: str) -> dict:
    if action not in ("accept", "reject", "cancel"):
        raise HTTPException(status_code=404, detail="Action must be accept/reject/cancel.")
    at = naive(now_utc())
    with SessionFactory() as s:
        svc = _trade_service(s)
        try:
            getattr(svc, action)(trade_id, at)
        except TransferError as exc:
            s.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
        status = svc.trades.get(trade_id).status.value
        s.commit()
        return {"ok": True, "status": status}


# ---------------------------------------------------------------------------
# Knockout picks (engine PickService: snapshot → pick from loser's snapshot)
# ---------------------------------------------------------------------------

class PickIn(BaseModel):
    knockout_fixture_id: int
    picker_manager_id: int
    picked_player_id: int


class SnapshotIn(BaseModel):
    manager_id: int
    fixture_id: int


def _pick_service(s) -> PickService:
    return PickService(
        rules=RULES, managers=SqlManagerRepo(s), players=SqlPlayerRepo(s),
        eligibility=_eligibility(s), snapshots=SqlSnapshotRepo(s),
        picks=SqlPickRepo(s))


@router.post("/picks/snapshot")
def take_snapshot(req: SnapshotIn) -> dict:
    """Freeze a manager's roster at knockout-match start (pick pool source)."""
    at = naive(now_utc())
    with SessionFactory() as s:
        _mgr_or_404(s, req.manager_id)
        if s.get(Fixture, req.fixture_id) is None:
            raise HTTPException(status_code=404, detail="Fixture not found.")
        snap_id = _pick_service(s).take_snapshot(req.manager_id, req.fixture_id, at)
        s.commit()
        return {"ok": True, "snapshot_id": snap_id}


@router.post("/picks")
def make_pick(req: PickIn) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        _mgr_or_404(s, req.picker_manager_id)
        _plr_or_404(s, req.picked_player_id)
        if s.get(Fixture, req.knockout_fixture_id) is None:
            raise HTTPException(status_code=404, detail="Fixture not found.")
        # Explicit KO-pick blacklist check (rule KNOCKOUT_PICK_BLACKLIST),
        # on top of the service's EligibilityService gate.
        blocked = [
            r for r in SqlEligibilityRepo(s).list_for_player(req.picked_player_id, at)
            if r.restriction_type is EligibilityRestriction.KNOCKOUT_PICK_BLACKLIST
            and r.manager_id == req.picker_manager_id
        ]
        if blocked:
            raise HTTPException(status_code=422,
                                detail="Player is blacklisted for this picker (KO pick).")
        try:
            pick_id = _pick_service(s).pick(
                req.knockout_fixture_id, req.picker_manager_id,
                req.picked_player_id, at)
        except MatchError as exc:
            s.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
        except EligibilityError as exc:
            s.rollback()
            raise HTTPException(status_code=422, detail=f"Eligibility: {exc}")
        s.commit()
        return {"ok": True, "pick_id": pick_id}


# ---------------------------------------------------------------------------
# Season seeding: managers, transfer windows, player catalogue import
# ---------------------------------------------------------------------------

class ManagerIn(BaseModel):
    display_name: str
    manager_name: str | None = None
    group_letter: str | None = None
    balance: int | None = None  # default: rules initial budget


@router.post("/managers")
def create_manager(req: ManagerIn) -> dict:
    with SessionFactory() as s:
        if s.scalars(select(Manager).where(Manager.display_name == req.display_name)).first():
            raise HTTPException(status_code=409, detail="Manager name already exists.")
        m = Manager(display_name=req.display_name, manager_name=req.manager_name,
                    group_letter=req.group_letter,
                    balance=req.balance if req.balance is not None
                    else RULES.managers.initial_budget,
                    cup_balance=RULES.cup.initial_cup_budget if RULES.cup.enabled else 0)
        s.add(m)
        s.commit()
        return {"id": m.id, "display_name": m.display_name,
                "manager_name": m.manager_name,
                "balance": m.balance, "cup_balance": m.cup_balance}


class ManagerPatch(BaseModel):
    manager_name: str | None = None


@router.patch("/managers/{manager_id}")
def update_manager(manager_id: int, req: ManagerPatch) -> dict:
    with SessionFactory() as s:
        m = s.get(Manager, manager_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Manager not found.")
        if req.manager_name is not None:
            m.manager_name = req.manager_name
        s.commit()
        return {"id": m.id, "display_name": m.display_name, "manager_name": m.manager_name}


class WindowIn(BaseModel):
    opens_at: str
    closes_at: str
    free_sign_period_seconds: int = 0


@router.post("/windows")
def create_window(req: WindowIn) -> dict:
    with SessionFactory() as s:
        w = TransferWindow(opens_at=parse_dt(req.opens_at), closes_at=parse_dt(req.closes_at),
                           free_sign_period_seconds=req.free_sign_period_seconds)
        s.add(w)
        s.commit()
        return {"id": w.id}


@router.post("/players/import")
async def import_players(file: UploadFile = File(...), dry_run: bool = Query(True)) -> dict:
    """Upsert the player catalogue. CSV columns: ID, Name, Nation, Pos
    (optionally JerseyNo, MarketValue). Round-trips with /api/export/players.csv."""
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    need = {"ID", "Name", "Nation", "Pos"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=422, detail=f"CSV must have columns {sorted(need)}.")
    created, updated, errors = 0, 0, []
    with SessionFactory() as s:
        for i, rec in enumerate(reader, start=2):
            try:
                pid = int(rec["ID"])
                pos = Position(rec["Pos"].strip())
            except (ValueError, KeyError) as exc:
                errors.append({"line": i, "error": str(exc)})
                continue
            p = s.get(Player, pid)
            if p is None:
                p = Player(id=pid, name=rec["Name"].strip(),
                           real_team=rec["Nation"].strip(), position=pos)
                s.add(p)
                created += 1
            else:
                p.name, p.real_team, p.position = rec["Name"].strip(), rec["Nation"].strip(), pos
                updated += 1
            if rec.get("JerseyNo"):
                p.jersey_no = int(rec["JerseyNo"])
            if rec.get("MarketValue"):
                p.market_value = int(rec["MarketValue"])
        if dry_run or errors:
            s.rollback()
        else:
            s.commit()
    return {"ok": not errors, "dry_run": dry_run, "created": created,
            "updated": updated, "errors": errors}
