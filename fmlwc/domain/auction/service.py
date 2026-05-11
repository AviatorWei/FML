"""End-to-end auction round orchestration.

Typical flow::

    svc = AuctionService(rules, ...)
    svc.open_round(round_id)
    svc.submit(round_id, manager_id, raw_bids, received_at)
    ...                                            # other managers submit
    svc.close_round(round_id, at=closes_at)        # status → RESOLVING
    resolution = svc.resolve(round_id, at=closes_at)

    # Optional: generate the public announcement text
    views = svc.announcement_views(round_id)
    from fmlwc.io.announcement import AuctionAnnouncementFormatter
    print(AuctionAnnouncementFormatter().format(views))

Everything from ``close_round`` onward must run in a single DB transaction
in the production SQL implementation; the in-memory fakes are used for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ...core.config import GameRules
from ...core.enums import AcquisitionVia, AuctionRoundStatus, BidStatus, Position
from ...persistence.repositories import (
    AuctionResultRepo,
    AuctionRoundRepo,
    BidRepo,
    EligibilityRepo,
    ManagerRepo,
    PlayerRepo,
    SubmissionRepo,
    TransferRepo,
)
from ..eligibility import EligibilityService
from .bids import BidValidator, RawBid, ValidationOutcome
from .cascade import CascadeContext, CascadeInvalidator
from .tiebreaker import CandidateBid, TiebreakerStrategy, deterministic_draw_seed, get_strategy


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class RoundResolution:
    """Returned by AuctionService.resolve."""

    round_id: int
    awards: list[tuple[int, int, int]]  # (player_id, winner_manager_id, price)
    invalidated: int                    # bids dropped by cascade
    total_spend: int                    # sum of winning prices


@dataclass(frozen=True)
class BidAnnouncementRow:
    """One row in the public announcement view — no DB refs, ready for formatting."""

    player_id: int
    player_name: str
    position: str        # "G" / "D" / "M" / "F"
    real_team: str       # e.g. "GER"
    rank_in_position: int
    amount: int          # million EUR
    manager_code: str    # display_name of the manager
    status: BidStatus


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AuctionService:
    """Orchestrates one sealed-bid auction round end-to-end."""

    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        bids: BidRepo,
        submissions: SubmissionRepo,
        rounds: AuctionRoundRepo,
        results: AuctionResultRepo,
        eligibility_repo: EligibilityRepo,
        eligibility_service: EligibilityService,
        transfer_repo: TransferRepo | None = None,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.bids = bids
        self.submissions = submissions
        self.rounds = rounds
        self.results = results
        self.eligibility_repo = eligibility_repo
        self.eligibility = eligibility_service
        self.transfer_repo = transfer_repo
        self.validator = BidValidator(rules, managers, players, eligibility_repo)
        self.cascade = CascadeInvalidator(rules)
        self.tiebreaker: TiebreakerStrategy = get_strategy(rules.auction.tiebreaker)

    # -- lifecycle -----------------------------------------------------------

    def open_round(self, round_id: int) -> None:
        """Mark the round OPEN so submissions can be accepted."""
        self.rounds.set_status(round_id, AuctionRoundStatus.OPEN)

    def submit(
        self,
        round_id: int,
        manager_id: int,
        raw_bids: Sequence[RawBid],
        received_at: datetime,
        *,
        source_file: str | None = None,
    ) -> int:
        """Validate bids and persist a Submission + Bid rows.

        Runs per-bid + rank-uniqueness validation (rule 二.3).  The
        (round_id, manager_id) submission is upserted, so re-submissions
        overwrite the prior one (rule 二.2).

        Returns
        -------
        submission_id
        """
        manager = self.managers.get(manager_id)
        balance_at_close = manager.balance

        outcomes = self.validator.validate_submission(
            list(raw_bids),
            balance_at_close=balance_at_close,
            at=received_at,
        )

        sub_id = self.submissions.upsert(round_id, manager_id, received_at, source_file)
        self.bids.clear_for_submission(sub_id)  # drop stale bids on re-submit

        for outcome in outcomes:
            bid_id = self.bids.create(
                sub_id,
                outcome.bid.player_id,
                outcome.bid.amount,
                outcome.bid.rank_in_position,
            )
            self.bids.update_status(bid_id, outcome.status, outcome.reason)

        return sub_id

    def close_round(self, round_id: int, *, at: datetime) -> None:
        """Freeze submissions; status → RESOLVING."""
        self.rounds.set_status(round_id, AuctionRoundStatus.RESOLVING)

    # -- resolution ----------------------------------------------------------

    def resolve(self, round_id: int, at: datetime) -> RoundResolution:
        """Run cascade per submission, then per-player tiebreaker, commit awards.

        Steps
        -----
        1. For each submission: build CascadeContext from DB bid statuses,
           run cascade, persist updated statuses.
        2. Group remaining VALID acquisition bids by player_id.
        3. Per player: tiebreaker → winner; mark AWARDED / LOST.
        4. Deduct winner balance; add to roster.
        5. Execute conditional releases (rule 二.X) if feature enabled.
        6. Record eligibility blocks for other managers (rule 二.7).
        7. Persist AuctionResult rows; mark round CLOSED.
        """
        all_submissions = self.submissions.for_round(round_id)

        # --- step 1: cascade per submission ---
        for sub in all_submissions:
            self._run_cascade_for_submission(sub, round_id)

        # --- step 2: collect VALID acquisition bids by player ---
        all_bids = self.bids.for_round(round_id)
        sub_map = {s.id: s for s in all_submissions}

        valid_by_player: dict[int, list[CandidateBid]] = {}
        for bid in all_bids:
            if bid.status is not BidStatus.VALID:
                continue
            if bid.rank_in_position < 0:   # conditional-release marker, not an acquisition
                continue
            sub = sub_map[bid.submission_id]
            candidate = CandidateBid(
                bid_id=bid.id,
                manager_id=sub.manager_id,
                amount=bid.amount,
                rank_in_position=bid.rank_in_position,
                submission_received_at=sub.received_at,
                draw_seed=deterministic_draw_seed(round_id, bid.player_id, sub.manager_id),
            )
            valid_by_player.setdefault(bid.player_id, []).append(candidate)

        # --- step 3–4: pick winners, settle ---
        next_window_close = self._next_window_close(at)
        awards: list[tuple[int, int, int]] = []
        wins_per_manager: dict[int, int] = {}

        for player_id in sorted(valid_by_player):
            candidates = valid_by_player[player_id]
            winner = self.tiebreaker.select_winner(candidates)

            for c in candidates:
                new_status = BidStatus.AWARDED if c is winner else BidStatus.LOST
                self.bids.update_status(c.bid_id, new_status)

            self.managers.adjust_balance(
                winner.manager_id, -winner.amount,
                reason=f"auction round {round_id} won player {player_id}",
            )
            self.managers.add_to_roster(
                winner.manager_id, player_id,
                acquired_at=at, via=AcquisitionVia.AUCTION, price=winner.amount,
            )

            wins_per_manager[winner.manager_id] = wins_per_manager.get(winner.manager_id, 0) + 1

            self.results.create(round_id, player_id, winner.manager_id, winner.amount)
            awards.append((player_id, winner.manager_id, winner.amount))

            # rule 二.7: block other managers until next transfer window
            self.eligibility.record_auction_block(
                except_winner_id=winner.manager_id,
                player_id=player_id,
                next_window_until=next_window_close,
            )

        # --- step 5: execute conditional releases ---
        if self.rules.auction.conditional_release_enabled and wins_per_manager:
            self._execute_conditional_releases(all_submissions, wins_per_manager, at)

        # --- step 7: close round ---
        self.rounds.set_status(round_id, AuctionRoundStatus.CLOSED)

        # --- build summary ---
        final_bids = self.bids.for_round(round_id)
        _invalid_statuses = {
            BidStatus.INVALID_PER_BID,
            BidStatus.INVALID_INELIGIBLE,
            BidStatus.INVALID_POS_CAP,
            BidStatus.INVALID_BUDGET,
        }
        invalidated = sum(1 for b in final_bids if b.status in _invalid_statuses)
        total_spend = sum(price for _, _, price in awards)

        return RoundResolution(
            round_id=round_id,
            awards=awards,
            invalidated=invalidated,
            total_spend=total_spend,
        )

    # -- public announcement view --------------------------------------------

    def announcement_views(self, round_id: int) -> list[BidAnnouncementRow]:
        """Return bid rows suitable for formatting as the public 暗标公示.

        Includes all bids that passed per-bid validation (VALID, cascade-
        invalidated, AWARDED, LOST).  Excludes INVALID_PER_BID and
        INVALID_INELIGIBLE (those failed format/eligibility checks and are
        not disclosed).  Conditional-release bids (rank < 0) are also
        excluded — they are internal roster-management instructions.

        Results are grouped by player_id (ascending), then sorted within
        each player by amount descending.
        """
        _show_statuses = {
            BidStatus.VALID,
            BidStatus.INVALID_POS_CAP,
            BidStatus.INVALID_BUDGET,
            BidStatus.AWARDED,
            BidStatus.LOST,
        }

        all_subs = self.submissions.for_round(round_id)
        sub_map = {s.id: s for s in all_subs}
        all_bids = self.bids.for_round(round_id)

        rows: list[BidAnnouncementRow] = []
        for bid in all_bids:
            if bid.status not in _show_statuses:
                continue
            if bid.rank_in_position < 0:
                continue
            sub = sub_map[bid.submission_id]
            player = self.players.get(bid.player_id)
            manager = self.managers.get(sub.manager_id)
            rows.append(BidAnnouncementRow(
                player_id=bid.player_id,
                player_name=player.name,
                position=player.position.value if hasattr(player.position, "value") else str(player.position),
                real_team=player.real_team,
                rank_in_position=bid.rank_in_position,
                amount=bid.amount,
                manager_code=manager.display_name,
                status=bid.status,
            ))

        # sort: player_id asc, then amount desc within same player
        rows.sort(key=lambda r: (r.player_id, -r.amount))
        return rows

    # -- private helpers -----------------------------------------------------

    def _run_cascade_for_submission(self, sub, round_id: int) -> None:
        """Load one manager's bids from DB, run cascade, persist results."""
        db_bids = self.bids.for_submission(sub.id)
        if not db_bids:
            return

        manager = self.managers.get(sub.manager_id)

        # Reconstruct ValidationOutcome list from stored statuses
        outcomes = [
            ValidationOutcome(
                bid=RawBid(
                    manager_id=sub.manager_id,
                    player_id=b.player_id,
                    amount=b.amount,
                    rank_in_position=b.rank_in_position,
                ),
                status=b.status,
                reason=b.invalid_reason,
            )
            for b in db_bids
        ]

        bid_positions = {
            b.player_id: self.players.get(b.player_id).position
            for b in db_bids
        }
        pos_counts = {
            pos: self.managers.position_count(sub.manager_id, pos)
            for pos in Position
        }
        roster = self.managers.list_roster(sub.manager_id)

        ctx = CascadeContext(
            manager_id=sub.manager_id,
            balance_at_close=manager.balance,
            current_position_counts=pos_counts,
            bids=outcomes,
            bid_positions=bid_positions,
            current_total_roster_count=len(roster),
        )
        results = self.cascade.run(ctx)

        for db_bid, outcome in zip(db_bids, results):
            if outcome.status != db_bid.status:
                self.bids.update_status(db_bid.id, outcome.status, outcome.reason)

    def _execute_conditional_releases(
        self,
        submissions: list,
        wins_per_manager: dict[int, int],
        at: datetime,
    ) -> None:
        """Release the top-N conditional-release players for each winning manager.

        If a manager won N bids, the players at ranks -1, -2, …, -N
        (from their conditional-release bids) are released, in that order.
        """
        for sub in submissions:
            win_count = wins_per_manager.get(sub.manager_id, 0)
            if win_count == 0:
                continue

            cr_bids = [
                b for b in self.bids.for_submission(sub.id)
                if b.rank_in_position < 0 and b.status is BidStatus.VALID
            ]
            # sort by rank descending so -1 comes first, -2 second, …
            cr_bids.sort(key=lambda b: b.rank_in_position, reverse=True)

            for cr_bid in cr_bids[:win_count]:
                self.managers.release_from_roster(sub.manager_id, cr_bid.player_id, at)
                self.eligibility.record_release_block(sub.manager_id, cr_bid.player_id)

    def _next_window_close(self, at: datetime) -> datetime | None:
        """Return the close time of the next (or current) transfer window, or None."""
        if self.transfer_repo is None:
            return None
        w = self.transfer_repo.current_window(at)
        if w:
            return w.closes_at
        w = self.transfer_repo.next_window(at)
        if w:
            return w.closes_at
        return None

    def _draw_seed(self, round_id: int, player_id: int, manager_id: int) -> int:
        return deterministic_draw_seed(round_id, player_id, manager_id)
