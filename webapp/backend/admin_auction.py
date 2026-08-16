"""Auction Desk — round lifecycle, sheet ingestion, dry-run resolve, commit.

Dry-run strategy: ``AuctionService.resolve`` mutates rows inside the open
session; with ``dry_run=true`` we collect the outcome and then ROLL BACK the
session instead of committing, so the report is exact without persisting.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from fmlwc.core.enums import AuctionRoundStatus
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.auction.service import AuctionService
from fmlwc.io.xlsx_bid_reader import XlsxBidParseError, XlsxBidReader
from fmlwc.persistence.models.auction import AuctionRound, Bid, Submission
from fmlwc.persistence.models.people import Manager, Player
from fmlwc.persistence.sql_repos import (
    SqlAuctionResultRepo,
    SqlAuctionRoundRepo,
    SqlBidRepo,
    SqlEligibilityRepo,
    SqlManagerRepo,
    SqlPlayerRepo,
    SqlSubmissionRepo,
    SqlTransferRepo,
)

from .deps import RULES, SessionFactory, naive, now_utc, parse_dt, require_admin

router = APIRouter(prefix="/api/admin/auction", tags=["admin:auction"],
                   dependencies=[Depends(require_admin)])


def _service(s) -> AuctionService:
    mgr, plr = SqlManagerRepo(s), SqlPlayerRepo(s)
    elig_repo = SqlEligibilityRepo(s)
    return AuctionService(
        rules=RULES, managers=mgr, players=plr,
        bids=SqlBidRepo(s), submissions=SqlSubmissionRepo(s),
        rounds=SqlAuctionRoundRepo(s), results=SqlAuctionResultRepo(s),
        eligibility_repo=elig_repo,
        eligibility_service=EligibilityService(RULES, mgr, plr, elig_repo),
        transfer_repo=SqlTransferRepo(s),
    )


def _round_or_404(s, round_id: int) -> AuctionRound:
    rnd = s.get(AuctionRound, round_id)
    if rnd is None:
        raise HTTPException(status_code=404, detail=f"Auction round {round_id} not found.")
    return rnd


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

class RoundCreate(BaseModel):
    index: int
    opens_at: str
    closes_at: str


@router.get("/rounds")
def list_rounds() -> dict:
    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        rounds = s.scalars(select(AuctionRound).order_by(AuctionRound.index)).all()
        out = []
        for rnd in rounds:
            subs = s.scalars(select(Submission).where(Submission.round_id == rnd.id)).all()
            out.append({
                "id": rnd.id, "index": rnd.index, "status": rnd.status.value,
                "opens_at": rnd.opens_at.isoformat(), "closes_at": rnd.closes_at.isoformat(),
                "submissions": [
                    {"manager_id": x.manager_id, "manager": names.get(x.manager_id),
                     "received_at": x.received_at.isoformat(), "source_file": x.source_file}
                    for x in subs
                ],
            })
    return {"rounds": out}


@router.post("/rounds")
def create_round(req: RoundCreate) -> dict:
    with SessionFactory() as s:
        dup = s.scalars(select(AuctionRound).where(AuctionRound.index == req.index)).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f"Round {req.index} already exists.")
        rnd = AuctionRound(index=req.index, opens_at=parse_dt(req.opens_at),
                           closes_at=parse_dt(req.closes_at),
                           status=AuctionRoundStatus.OPEN)
        s.add(rnd)
        s.commit()
        return {"id": rnd.id, "index": rnd.index, "status": rnd.status.value}


# ---------------------------------------------------------------------------
# Sheet ingestion — parse xlsx files, persist Submission + Bid rows
# ---------------------------------------------------------------------------

@router.post("/rounds/{round_id}/submissions")
async def upload_submissions(round_id: int, files: list[UploadFile] = File(...)) -> dict:
    at = naive(now_utc())
    reports = []
    with SessionFactory() as s:
        rnd = _round_or_404(s, round_id)
        if rnd.status is AuctionRoundStatus.CLOSED:
            raise HTTPException(status_code=409, detail="Round is CLOSED; no more submissions.")
        svc = _service(s)
        code_to_mgr = {m.display_name: m for m in s.scalars(select(Manager))}

        for up in files:
            report = {"file": up.filename, "ok": False, "manager": None,
                      "bids": 0, "total": 0, "warnings": [], "error": None}
            reports.append(report)
            if not up.filename or not up.filename.lower().endswith(".xlsx"):
                report["error"] = "not an .xlsx file"
                continue
            data = await up.read()
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / up.filename
                    path.write_bytes(data)
                    sub = XlsxBidReader(tmp).read_file(up.filename)
            except (XlsxBidParseError, Exception) as exc:  # noqa: BLE001
                report["error"] = f"parse failed: {exc}"
                continue

            mgr = code_to_mgr.get(sub.manager_code)
            if mgr is None:
                report["error"] = f"manager code {sub.manager_code!r} not found"
                continue
            if sub.round_index != rnd.index:
                report["warnings"].append(
                    f"filename says round {sub.round_index}, uploading into round {rnd.index}")

            raw_bids = sub.to_raw_bids(mgr.id)
            try:
                svc.submit(rnd.id, mgr.id, raw_bids, at, source_file=sub.source_file)
            except Exception as exc:  # noqa: BLE001 — engine validation error
                report["error"] = f"submission rejected: {exc}"
                continue
            report.update(ok=True, manager=sub.manager_code,
                          bids=len(raw_bids), total=sum(b.amount for b in raw_bids))
            low = [b for b in raw_bids
                   if b.rank_in_position > 0 and b.amount < RULES.auction.min_bid]
            if low:
                report["warnings"].append(
                    f"{len(low)} bid(s) below min bid {RULES.auction.min_bid}m "
                    "(will be invalidated per rule 二.3)")
        s.commit()
    return {"round_id": round_id, "files": reports}


# ---------------------------------------------------------------------------
# Bids view (current statuses)
# ---------------------------------------------------------------------------

def _bid_report(s, round_id: int) -> list[dict]:
    subs = {x.id: x for x in s.scalars(select(Submission).where(Submission.round_id == round_id))}
    names = {m.id: m.display_name for m in s.scalars(select(Manager))}
    players = {p.id: p for p in s.scalars(select(Player))}
    bids = s.scalars(select(Bid).where(Bid.submission_id.in_(list(subs) or [-1]))).all()
    out = []
    for b in bids:
        sub = subs[b.submission_id]
        p = players.get(b.player_id)
        out.append({
            "bid_id": b.id, "manager": names.get(sub.manager_id),
            "manager_id": sub.manager_id,
            "player_id": b.player_id, "player": p.name if p else None,
            "position": p.position.value if p else None,
            "real_team": p.real_team if p else None,
            "amount": b.amount, "rank": b.rank_in_position,
            "status": b.status.value, "reason": b.invalid_reason,
        })
    out.sort(key=lambda x: (x["player_id"], -x["amount"]))
    return out


@router.get("/rounds/{round_id}/bids")
def round_bids(round_id: int) -> dict:
    with SessionFactory() as s:
        _round_or_404(s, round_id)
        return {"round_id": round_id, "bids": _bid_report(s, round_id)}


# ---------------------------------------------------------------------------
# Resolve — dry run (rollback) or commit
# ---------------------------------------------------------------------------

@router.post("/rounds/{round_id}/resolve")
def resolve_round(round_id: int, dry_run: bool = Query(True)) -> dict:
    at = naive(now_utc())
    with SessionFactory() as s:
        rnd = _round_or_404(s, round_id)
        if rnd.status is AuctionRoundStatus.CLOSED:
            raise HTTPException(status_code=409, detail="Round already resolved (CLOSED).")
        svc = _service(s)
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        balances_before = {m.id: m.balance for m in s.scalars(select(Manager))}
        players = {p.id: p.name for p in s.scalars(select(Player))}

        svc.close_round(rnd.id, at=at)
        try:
            resolution = svc.resolve(rnd.id, at)
        except NotImplementedError as exc:
            s.rollback()
            raise HTTPException(
                status_code=501,
                detail=f"Engine service not implemented yet: {exc}")
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            raise HTTPException(status_code=422, detail=f"Resolve failed: {exc}")

        bid_rows = _bid_report(s, round_id)
        deltas = [
            {"manager": names.get(mid), "before": before,
             "after": next(m.balance for m in s.scalars(
                 select(Manager).where(Manager.id == mid)))}
            for mid, before in balances_before.items()
        ]
        report = {
            "round_id": round_id, "dry_run": dry_run,
            "awards": [
                {"player_id": pid, "player": players.get(pid),
                 "winner": names.get(mid), "price": price}
                for pid, mid, price in resolution.awards
            ],
            "invalidated": resolution.invalidated,
            "total_spend": resolution.total_spend,
            "bids": bid_rows,
            "balance_deltas": [d for d in deltas if d["before"] != d["after"]],
        }
        if dry_run:
            s.rollback()
        else:
            s.commit()
        return report
