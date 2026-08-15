"""Export center — every league artefact as a GET-a-file endpoint.

All endpoints live under /api/export/*. Formats: xlsx (openpyxl), csv
(UTF-8 with BOM), txt, json, zip.
"""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from fmlwc.domain.auction.service import AuctionService
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.io.announcement import AuctionAnnouncementFormatter
from fmlwc.io.player_list_exporter import query_player_list
from fmlwc.persistence.models.auction import AuctionResult, AuctionRound
from fmlwc.persistence.models.knockout import RosterSnapshot
from fmlwc.persistence.models.match import (
    BonusAward,
    Fixture,
    Gameweek,
    Lineup,
    ManagerPlayerAthletics,
    ManagerStats,
    MatchEvent,
    MatchResult,
    PlayerAthletics,
)
from fmlwc.persistence.models.people import Manager, Player, RosterEntry
from fmlwc.persistence.models.transfer import (
    Dismissal,
    FreeSign,
    Release,
    Trade,
    TradeLeg,
)
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

from .deps import RULES, XLSX_MIME, SessionFactory, build_csv, build_xlsx, file_response, now_utc

router = APIRouter(prefix="/api/export", tags=["export"])

_STATS = ("goals", "own_goals", "saved_penalties", "missed_penalties",
          "assists", "yellows", "second_yellow_reds", "reds")


def _season_year() -> int:
    return getattr(RULES.scope, "year", None) or now_utc().year


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@router.get("/manifest")
def manifest() -> dict:
    with SessionFactory() as s:
        counts = {
            "players": s.scalar(select(func.count()).select_from(Player)) or 0,
            "managers": s.scalar(select(func.count()).select_from(Manager)) or 0,
            "roster_entries": s.scalar(select(func.count()).select_from(RosterEntry)) or 0,
            "roster_snapshots": s.scalar(select(func.count()).select_from(RosterSnapshot)) or 0,
            "auction_rounds": s.scalar(select(func.count()).select_from(AuctionRound)) or 0,
            "auction_results": s.scalar(select(func.count()).select_from(AuctionResult)) or 0,
            "lineups": s.scalar(select(func.count()).select_from(Lineup)) or 0,
            "events": s.scalar(select(func.count()).select_from(MatchEvent)) or 0,
            "results": s.scalar(select(func.count()).select_from(MatchResult)) or 0,
            "free_signs": s.scalar(select(func.count()).select_from(FreeSign)) or 0,
            "trades": s.scalar(select(func.count()).select_from(Trade)) or 0,
            "releases": s.scalar(select(func.count()).select_from(Release)) or 0,
            "dismissals": s.scalar(select(func.count()).select_from(Dismissal)) or 0,
            "bonus_awards": s.scalar(select(func.count()).select_from(BonusAward)) or 0,
        }
        rounds = [r.index for r in s.scalars(select(AuctionRound).order_by(AuctionRound.index))]
        gameweeks = [g.index for g in s.scalars(select(Gameweek).order_by(Gameweek.index))]
    return {"generated_at": now_utc().isoformat(), "counts": counts,
            "auction_rounds": rounds, "gameweeks": gameweeks,
            "season_year": _season_year()}


# ---------------------------------------------------------------------------
# Player list (PlayerListExporter format: ID | Name | Nation | Pos | Team | Price)
# ---------------------------------------------------------------------------

def _player_list_rows(s) -> tuple[list[str], list[list]]:
    rows = query_player_list(s)
    headers = ["ID", "Name", "Nation", "Pos", "Team", "Price"]
    data = [[r.player_id, r.name, r.nation, r.position, r.manager_code, r.price] for r in rows]
    return headers, data


@router.get("/players.xlsx")
def players_xlsx():
    with SessionFactory() as s:
        headers, data = _player_list_rows(s)
    return file_response(build_xlsx({"Sheet1": (headers, data)}), "player_list.xlsx", XLSX_MIME)


@router.get("/players.csv")
def players_csv():
    with SessionFactory() as s:
        headers, data = _player_list_rows(s)
    return file_response(build_csv(headers, data), "player_list.csv", "text/csv")


# ---------------------------------------------------------------------------
# Bid templates (mirror of XlsxBidReader sheet layout)
# ---------------------------------------------------------------------------

def _bid_template_bytes(s, round_index: int) -> bytes:
    """One sheet: Order | Price | ID | Name | Team | Pos — rows = free agents."""
    players = s.scalars(select(Player).order_by(Player.id)).all()
    owned = {
        e.player_id for e in s.scalars(
            select(RosterEntry).where(RosterEntry.released_at.is_(None))
        )
    }
    headers = ["Order", "Price", "ID", "Name", "Team", "Pos"]
    rows = [
        [None, None, p.id, p.name, p.real_team, p.position.value]
        for p in players if p.id not in owned
    ]
    return build_xlsx({"Sheet1": (headers, rows)})


@router.get("/bid-template")
def bid_template(round: int = Query(..., ge=1), manager_code: str | None = None):
    year = _season_year()
    with SessionFactory() as s:
        data = _bid_template_bytes(s, round)
        if manager_code:
            mgr = s.scalars(select(Manager).where(Manager.display_name == manager_code)).first()
            if mgr is None:
                raise HTTPException(status_code=404, detail=f"Manager code {manager_code!r} not found.")
            fname = f"FME_{year}_Bid{round}_{manager_code}.xlsx"
            return file_response(data, fname, XLSX_MIME)
        codes = [m.display_name for m in s.scalars(select(Manager).order_by(Manager.display_name))]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for code in codes:
            z.writestr(f"FME_{year}_Bid{round}_{code}.xlsx", data)
    return file_response(buf.getvalue(), f"FME_{year}_Bid{round}_templates.zip", "application/zip")


# ---------------------------------------------------------------------------
# Auction: announcement 暗标公示 + results
# ---------------------------------------------------------------------------

def _auction_service(s) -> AuctionService:
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


def _round_by_index(s, round_index: int) -> AuctionRound:
    rnd = s.scalars(select(AuctionRound).where(AuctionRound.index == round_index)).first()
    if rnd is None:
        raise HTTPException(status_code=404, detail=f"Auction round {round_index} not found.")
    return rnd


@router.get("/auction/{round_index}/announcement.txt")
def auction_announcement(round_index: int):
    with SessionFactory() as s:
        rnd = _round_by_index(s, round_index)
        views = _auction_service(s).announcement_views(rnd.id)
        text = AuctionAnnouncementFormatter().format(views)
    return file_response(text.encode("utf-8"), f"announcement_round{round_index}.txt",
                         "text/plain; charset=utf-8")


def _auction_results_rows(s, rnd) -> tuple[list[str], list[list]]:
    names = {m.id: m.display_name for m in s.scalars(select(Manager))}
    players = {p.id: p for p in s.scalars(select(Player))}
    headers = ["Round", "PlayerID", "Player", "Pos", "Nation", "Winner", "Price"]
    rows = []
    for r in s.scalars(select(AuctionResult).where(AuctionResult.round_id == rnd.id)):
        p = players.get(r.player_id)
        rows.append([rnd.index, r.player_id, p.name if p else None,
                     p.position.value if p else None, p.real_team if p else None,
                     names.get(r.winner_manager_id), r.price])
    rows.sort(key=lambda x: -x[6])
    return headers, rows


@router.get("/auction/{round_index}/results.csv")
def auction_results_csv(round_index: int):
    with SessionFactory() as s:
        headers, rows = _auction_results_rows(s, _round_by_index(s, round_index))
    return file_response(build_csv(headers, rows), f"auction_round{round_index}_results.csv", "text/csv")


@router.get("/auction/{round_index}/results.xlsx")
def auction_results_xlsx(round_index: int):
    with SessionFactory() as s:
        headers, rows = _auction_results_rows(s, _round_by_index(s, round_index))
    return file_response(build_xlsx({"Results": (headers, rows)}),
                         f"auction_round{round_index}_results.xlsx", XLSX_MIME)


# ---------------------------------------------------------------------------
# Rosters + snapshots
# ---------------------------------------------------------------------------

def _roster_rows(s, manager_id: int | None, include_released: bool) -> tuple[list[str], list[list]]:
    names = {m.id: m.display_name for m in s.scalars(select(Manager))}
    players = {p.id: p for p in s.scalars(select(Player))}
    stmt = select(RosterEntry).order_by(RosterEntry.manager_id, RosterEntry.id)
    if manager_id is not None:
        stmt = stmt.where(RosterEntry.manager_id == manager_id)
    if not include_released:
        stmt = stmt.where(RosterEntry.released_at.is_(None))
    headers = ["Manager", "PlayerID", "Player", "Pos", "Nation",
               "Via", "Price", "AcquiredAt", "ReleasedAt"]
    rows = []
    for e in s.scalars(stmt):
        p = players.get(e.player_id)
        rows.append([
            names.get(e.manager_id), e.player_id, p.name if p else None,
            p.position.value if p else None, p.real_team if p else None,
            e.acquired_via.value, e.acquired_price,
            e.acquired_at.isoformat(sep=" "),
            e.released_at.isoformat(sep=" ") if e.released_at else None,
        ])
    return headers, rows


@router.get("/rosters.xlsx")
def rosters_xlsx(manager_id: int | None = None, include_released: bool = False):
    with SessionFactory() as s:
        headers, rows = _roster_rows(s, manager_id, include_released)
    return file_response(build_xlsx({"Rosters": (headers, rows)}), "rosters.xlsx", XLSX_MIME)


@router.get("/rosters.csv")
def rosters_csv(manager_id: int | None = None, include_released: bool = False):
    with SessionFactory() as s:
        headers, rows = _roster_rows(s, manager_id, include_released)
    return file_response(build_csv(headers, rows), "rosters.csv", "text/csv")


@router.get("/roster-snapshots.json")
def roster_snapshots():
    import json

    with SessionFactory() as s:
        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        out = [
            {"id": r.id, "manager": names.get(r.manager_id),
             "taken_at": r.taken_at.isoformat(), "reason": r.reason, "entries": r.entries}
            for r in s.scalars(select(RosterSnapshot).order_by(RosterSnapshot.taken_at))
        ]
    return file_response(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"),
                         "roster_snapshots.json", "application/json")


# ---------------------------------------------------------------------------
# Lineups + events (CSV round-trips with the import endpoints)
# ---------------------------------------------------------------------------

def _lineup_rows(s, gameweek: int | None) -> tuple[list[str], list[list]]:
    names = {m.id: m.display_name for m in s.scalars(select(Manager))}
    players = {p.id: p.name for p in s.scalars(select(Player))}
    gws = {g.id: g.index for g in s.scalars(select(Gameweek))}
    fixtures = {f.id: f for f in s.scalars(select(Fixture))}
    headers = ["Gameweek", "Manager", "FixtureID", "PlayerID", "Player", "Slot",
               "PkOrder", "PostedAt"]
    rows = []
    for lu in s.scalars(select(Lineup).order_by(Lineup.fixture_id, Lineup.manager_id)):
        fx = fixtures.get(lu.fixture_id)
        gw_index = gws.get(fx.gameweek_id) if fx else None
        if gameweek is not None and gw_index != gameweek:
            continue
        pk = lu.pk_order or []
        for st in (lu.starters or []):
            pid, slot = st.get("player_id"), st.get("slot_position")
            rows.append([gw_index, names.get(lu.manager_id), lu.fixture_id,
                         pid, players.get(pid), slot,
                         pk.index(pid) + 1 if pid in pk else None,
                         lu.posted_at.isoformat(sep=" ")])
    return headers, rows


@router.get("/lineups.csv")
def lineups_csv(gameweek: int | None = None):
    with SessionFactory() as s:
        headers, rows = _lineup_rows(s, gameweek)
    return file_response(build_csv(headers, rows), "lineups.csv", "text/csv")


def _event_rows(s, gameweek: int | None) -> tuple[list[str], list[list]]:
    players = {p.id: p.name for p in s.scalars(select(Player))}
    gws = {g.id: g.index for g in s.scalars(select(Gameweek))}
    stmt = select(MatchEvent).order_by(MatchEvent.gameweek_id, MatchEvent.id)
    headers = ["gameweek", "player_id", "player_name", "event_type",
               "minute", "is_extra_time", "is_shootout"]
    rows = []
    for e in s.scalars(stmt):
        gw_index = gws.get(e.gameweek_id)
        if gameweek is not None and gw_index != gameweek:
            continue
        rows.append([gw_index, e.player_id, players.get(e.player_id),
                     e.event_type.value, e.minute,
                     int(e.is_extra_time), int(e.is_shootout)])
    return headers, rows


@router.get("/events.csv")
def events_csv(gameweek: int | None = None):
    with SessionFactory() as s:
        headers, rows = _event_rows(s, gameweek)
    return file_response(build_csv(headers, rows), "events.csv", "text/csv")


# ---------------------------------------------------------------------------
# Standings + results
# ---------------------------------------------------------------------------

def _standings_sheets(s) -> dict[str, tuple[list[str], list[list]]]:
    from .standings import compute_standings, sort_table as _sort_table

    rows = list(compute_standings(s).values())
    headers = ["Rank", "Manager", "Group", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]

    def tab(rs):
        return [[r["rank"], r["name"], r["group"], r["played"], r["win"], r["draw"],
                 r["loss"], r["gf"], r["ga"], r["gd"], r["points"]] for r in _sort_table(rs)]

    sheets: dict[str, tuple[list[str], list[list]]] = {"League": (headers, tab(list(rows)))}
    groups: dict[str, list] = {}
    for r in rows:
        if r["group"]:
            groups.setdefault(r["group"], []).append(r)
    for g in sorted(groups):
        sheets[f"Group {g}"] = (headers, tab(groups[g]))

    names = {m.id: m.display_name for m in s.scalars(select(Manager))}
    gws = {g.id: g.index for g in s.scalars(select(Gameweek))}
    res_headers = ["Gameweek", "FixtureID", "Group", "Slot", "Home", "Away",
                   "HomeGoals", "AwayGoals", "Outcome", "PKWinner", "LockedAt"]
    res_rows = []
    q = select(MatchResult, Fixture).join(Fixture, MatchResult.fixture_id == Fixture.id)
    for res, fx in s.execute(q):
        res_rows.append([gws.get(fx.gameweek_id), fx.id, fx.group_letter, fx.bracket_slot,
                         names.get(fx.home_manager_id), names.get(fx.away_manager_id),
                         res.home_goals, res.away_goals, res.outcome.value,
                         names.get(res.pk_winner_id),
                         res.locked_at.isoformat(sep=" ") if res.locked_at else None])
    sheets["Results"] = (res_headers, res_rows)
    return sheets


@router.get("/standings.xlsx")
def standings_xlsx():
    with SessionFactory() as s:
        sheets = _standings_sheets(s)
    return file_response(build_xlsx(sheets), "standings.xlsx", XLSX_MIME)


@router.get("/standings.csv")
def standings_csv():
    with SessionFactory() as s:
        headers, rows = _standings_sheets(s)["League"]
    return file_response(build_csv(headers, rows), "standings_league.csv", "text/csv")


# ---------------------------------------------------------------------------
# Athletics (3 sheets)
# ---------------------------------------------------------------------------

@router.get("/athletics.xlsx")
def athletics_xlsx():
    with SessionFactory() as s:
        pnames = {p.id: p.name for p in s.scalars(select(Player))}
        mnames = {m.id: m.display_name for m in s.scalars(select(Manager))}
        ph = ["PlayerID", "Player", *_STATS]
        prow = [[a.player_id, pnames.get(a.player_id), *[getattr(a, f) for f in _STATS]]
                for a in s.scalars(select(PlayerAthletics))]
        mh = ["Manager", *_STATS]
        mrow = [[mnames.get(a.manager_id), *[getattr(a, f) for f in _STATS]]
                for a in s.scalars(select(ManagerStats))]
        mph = ["Manager", "PlayerID", "Player", *_STATS]
        mprow = [[mnames.get(a.manager_id), a.player_id, pnames.get(a.player_id),
                  *[getattr(a, f) for f in _STATS]]
                 for a in s.scalars(select(ManagerPlayerAthletics))]
    return file_response(
        build_xlsx({"Players": (ph, prow), "Managers": (mh, mrow), "PerPair": (mph, mprow)}),
        "athletics.xlsx", XLSX_MIME)


# ---------------------------------------------------------------------------
# Transfer ledger (4 sheets)
# ---------------------------------------------------------------------------

@router.get("/transfers.xlsx")
def transfers_xlsx():
    with SessionFactory() as s:
        mnames = {m.id: m.display_name for m in s.scalars(select(Manager))}
        pnames = {p.id: p.name for p in s.scalars(select(Player))}

        fs_h = ["ID", "WindowID", "Manager", "Player", "Fee", "PostedAt", "Revoked", "Effective"]
        fs_r = [[f.id, f.window_id, mnames.get(f.manager_id), pnames.get(f.player_id),
                 f.fee, f.posted_at.isoformat(sep=" "), int(f.revoked), int(f.effective)]
                for f in s.scalars(select(FreeSign).order_by(FreeSign.posted_at))]

        legs: dict[int, list[str]] = {}
        for leg in s.scalars(select(TradeLeg)):
            what = pnames.get(leg.player_id) if leg.player_id else f"{leg.cash_amount}m cash"
            legs.setdefault(leg.trade_id, []).append(f"{leg.side.value}: {what}")
        tr_h = ["ID", "WindowID", "Initiator", "Counterparty", "Status", "Legs",
                "ProposedAt", "ResolvedAt"]
        tr_r = [[t.id, t.window_id, mnames.get(t.initiator_id), mnames.get(t.counterparty_id),
                 t.status.value, " | ".join(legs.get(t.id, [])),
                 t.proposed_at.isoformat(sep=" "),
                 t.resolved_at.isoformat(sep=" ") if t.resolved_at else None]
                for t in s.scalars(select(Trade).order_by(Trade.proposed_at))]

        rl_h = ["ID", "Manager", "Player", "PostedAt", "Revoked", "Effective"]
        rl_r = [[r.id, mnames.get(r.manager_id), pnames.get(r.player_id),
                 r.posted_at.isoformat(sep=" "), int(r.revoked), int(r.effective)]
                for r in s.scalars(select(Release).order_by(Release.posted_at))]

        dm_h = ["ID", "Manager", "Player", "DismissedAt", "Reason"]
        dm_r = [[d.id, mnames.get(d.manager_id), pnames.get(d.player_id),
                 d.dismissed_at.isoformat(sep=" "), d.reason]
                for d in s.scalars(select(Dismissal).order_by(Dismissal.dismissed_at))]
    return file_response(
        build_xlsx({"FreeSigns": (fs_h, fs_r), "Trades": (tr_h, tr_r),
                    "Releases": (rl_h, rl_r), "Dismissals": (dm_h, dm_r)}),
        "transfers.xlsx", XLSX_MIME)


# ---------------------------------------------------------------------------
# Prize / bonus ledger
# ---------------------------------------------------------------------------

@router.get("/prizes.csv")
def prizes_csv():
    with SessionFactory() as s:
        mnames = {m.id: m.display_name for m in s.scalars(select(Manager))}
        headers = ["ID", "FixtureID", "Manager", "BonusType", "Amount"]
        rows = [[b.id, b.fixture_id, mnames.get(b.manager_id), b.bonus_type, b.amount]
                for b in s.scalars(select(BonusAward).order_by(BonusAward.id))]
    return file_response(build_csv(headers, rows), "prizes.csv", "text/csv")


# ---------------------------------------------------------------------------
# Full season archive
# ---------------------------------------------------------------------------

@router.get("/season.zip")
def season_zip():
    import json

    buf = io.BytesIO()
    with SessionFactory() as s, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        h, r = _player_list_rows(s)
        z.writestr("player_list.xlsx", build_xlsx({"Sheet1": (h, r)}))
        h, r = _roster_rows(s, None, True)
        z.writestr("rosters.xlsx", build_xlsx({"Rosters": (h, r)}))
        h, r = _lineup_rows(s, None)
        z.writestr("lineups.csv", build_csv(h, r))
        h, r = _event_rows(s, None)
        z.writestr("events.csv", build_csv(h, r))
        z.writestr("standings.xlsx", build_xlsx(_standings_sheets(s)))

        svc = _auction_service(s)
        fmt = AuctionAnnouncementFormatter()
        for rnd in s.scalars(select(AuctionRound).order_by(AuctionRound.index)):
            hh, rr = _auction_results_rows(s, rnd)
            z.writestr(f"auction/round{rnd.index}_results.csv", build_csv(hh, rr))
            try:
                z.writestr(f"auction/round{rnd.index}_announcement.txt",
                           fmt.format(svc.announcement_views(rnd.id)).encode("utf-8"))
            except Exception:
                pass  # round without bids

        names = {m.id: m.display_name for m in s.scalars(select(Manager))}
        snaps = [{"id": x.id, "manager": names.get(x.manager_id),
                  "taken_at": x.taken_at.isoformat(), "reason": x.reason, "entries": x.entries}
                 for x in s.scalars(select(RosterSnapshot))]
        z.writestr("roster_snapshots.json", json.dumps(snaps, ensure_ascii=False, indent=2))
    return file_response(buf.getvalue(), "fmlwc_season.zip", "application/zip")
