"""Multi-player + cash trades between managers.

Trade legs are two-sided; either side may include any number of players
and any cash amount. Eligibility is checked for the receiving manager on
every player they take in; balance check applies to the cash legs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ...core.config import GameRules
from ...core.enums import AcquisitionVia, TradeStatus
from ...core.exceptions import EligibilityError, TransferError
from ...persistence.repositories import ManagerRepo, PlayerRepo, TradeRepo, TransferRepo
from ..eligibility import EligibilityService

_SIDES = ("INITIATOR", "COUNTERPARTY")


@dataclass(frozen=True)
class TradeLegInput:
    side: str                        # "INITIATOR" | "COUNTERPARTY"
    player_id: int | None = None     # exactly one of player_id / cash_amount
    cash_amount: int | None = None


class TradeService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        eligibility: EligibilityService,
        trades: TradeRepo | None = None,
        transfers: TransferRepo | None = None,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.eligibility = eligibility
        self.trades = trades
        self.transfers = transfers

    # -- helpers ------------------------------------------------------------------

    def _require_repo(self) -> TradeRepo:
        if self.trades is None:
            raise TransferError("TradeService requires a TradeRepo")
        return self.trades

    def _owns(self, manager_id: int, player_id: int) -> bool:
        return any(e.player_id == player_id for e in self.managers.list_roster(manager_id))

    def _check_legs_shape(self, legs: Sequence[TradeLegInput]) -> None:
        if not legs:
            raise TransferError("a trade needs at least one leg")
        for leg in legs:
            if leg.side not in _SIDES:
                raise TransferError(f"bad trade side {leg.side!r}")
            if (leg.player_id is None) == (leg.cash_amount is None):
                raise TransferError(
                    "each leg must carry exactly one of player_id / cash_amount"
                )
            if leg.cash_amount is not None:
                if not self.rules.transfer.trades_allow_cash:
                    raise TransferError("cash legs are disabled by rules")
                if leg.cash_amount <= 0:
                    raise TransferError("cash amount must be positive")

        # 第四十九条(2): pure players-for-cash requires ≥ min_cash_per_player
        # for every player moved.
        min_cash = self.rules.transfer.min_cash_per_player
        if min_cash:
            sides_with_players = {l.side for l in legs if l.player_id is not None}
            sides_with_cash = {l.side for l in legs if l.cash_amount is not None}
            if len(sides_with_players) == 1 and sides_with_cash and \
                    sides_with_players.isdisjoint(sides_with_cash):
                n_players = sum(1 for l in legs if l.player_id is not None)
                total_cash = sum(l.cash_amount or 0 for l in legs)
                if total_cash < min_cash * n_players:
                    raise TransferError(
                        f"players-for-cash trades need at least {min_cash}m "
                        f"per player ({n_players} players → ≥ "
                        f"{min_cash * n_players}m, got {total_cash}m)")

    def _check_trade_limits(self, trade, legs: Sequence[TradeLegInput]) -> None:
        """FML 第五十条/第六十一条: ownership + per-window trade caps."""
        repo = self.trades
        if repo is None:
            return
        recipient = {"INITIATOR": trade.counterparty_id,
                     "COUNTERPARTY": trade.initiator_id}
        max_owners = self.rules.transfer.max_owners_per_season
        max_per_window = self.rules.transfer.max_trades_per_window_per_player
        for leg in legs:
            if leg.player_id is None:
                continue
            if max_owners:
                owners = repo.distinct_owners(leg.player_id)
                if recipient[leg.side] not in owners and len(owners) >= max_owners:
                    raise TransferError(
                        f"player {leg.player_id} has already belonged to "
                        f"{len(owners)} managers (season cap {max_owners}, "
                        "第五十条)")
            if max_per_window and trade.window_id is not None:
                n = repo.accepted_trades_in_window(leg.player_id, trade.window_id)
                if n >= max_per_window:
                    raise TransferError(
                        f"player {leg.player_id} was already traded in this "
                        f"window (cap {max_per_window}, 第五十条)")

    def _validate_sides(
        self, initiator_id: int, counterparty_id: int,
        legs: Sequence[TradeLegInput], at: datetime, *, both_sides: bool,
    ) -> None:
        giver = {"INITIATOR": initiator_id, "COUNTERPARTY": counterparty_id}
        recipient = {"INITIATOR": counterparty_id, "COUNTERPARTY": initiator_id}
        cash_out: dict[int, int] = {}
        for leg in legs:
            if not both_sides and leg.side != "INITIATOR":
                continue  # at proposal time only the initiator's side is checked
            if leg.player_id is not None:
                if not self._owns(giver[leg.side], leg.player_id):
                    raise TransferError(
                        f"player {leg.player_id} is not on the {leg.side} roster"
                    )
                if both_sides:
                    self.eligibility.assert_allowed(
                        recipient[leg.side], leg.player_id,
                        AcquisitionVia.TRADE, fee=0, at=at,
                    )
            else:
                cash_out[giver[leg.side]] = cash_out.get(giver[leg.side], 0) + leg.cash_amount
        for mgr_id, total in cash_out.items():
            if self.managers.get(mgr_id).balance < total:
                raise TransferError(
                    f"manager {mgr_id} cannot cover {total}m in cash legs"
                )

    # -- public API -------------------------------------------------------------------

    def propose(
        self,
        initiator_id: int,
        counterparty_id: int,
        legs: Sequence[TradeLegInput],
        proposed_at: datetime,
    ) -> int:
        """Persist Trade in PROPOSED state. No state change to either roster
        until accept().

        Pre-checks: an open transfer window (when a TransferRepo is wired),
        legs well-formed, initiator owns the players they offer.
        """
        repo = self._require_repo()
        if initiator_id == counterparty_id:
            raise TransferError("cannot trade with yourself")
        window_id = None
        if self.transfers is not None:
            window = self.transfers.current_window(proposed_at)
            if window is None:
                raise TransferError("no transfer window open at this time")
            window_id = window.id
        self._check_legs_shape(legs)
        self._validate_sides(initiator_id, counterparty_id, legs, proposed_at,
                             both_sides=False)
        return repo.create(window_id, initiator_id, counterparty_id, legs, proposed_at)

    def accept(self, trade_id: int, at: datetime) -> None:
        """Atomic swap. All-or-nothing. Re-runs ownership, eligibility and
        balance checks on both sides at acceptance time (situations may have
        changed since proposal), then moves roster entries and cash."""
        repo = self._require_repo()
        trade = repo.get(trade_id)
        if trade is None:
            raise TransferError(f"trade {trade_id} not found")
        if trade.status is not TradeStatus.PROPOSED:
            raise TransferError(f"trade {trade_id} is {trade.status.value}, not PROPOSED")

        legs = [
            TradeLegInput(
                side=leg.side.value if hasattr(leg.side, "value") else leg.side,
                player_id=leg.player_id,
                cash_amount=leg.cash_amount,
            )
            for leg in repo.legs_for(trade_id)
        ]
        self._check_legs_shape(legs)
        self._check_trade_limits(trade, legs)
        try:
            self._validate_sides(trade.initiator_id, trade.counterparty_id, legs, at,
                                 both_sides=True)
        except EligibilityError as exc:
            raise TransferError(f"eligibility check failed at acceptance: {exc}") from exc

        giver = {"INITIATOR": trade.initiator_id, "COUNTERPARTY": trade.counterparty_id}
        recipient = {"INITIATOR": trade.counterparty_id, "COUNTERPARTY": trade.initiator_id}
        for leg in legs:
            if leg.player_id is not None:
                self.managers.release_from_roster(giver[leg.side], leg.player_id, at)
                self.managers.add_to_roster(
                    recipient[leg.side], leg.player_id,
                    acquired_at=at, via=AcquisitionVia.TRADE, price=0,
                )
                # 第五十一条: a player traded away can never be re-signed by
                # the giving manager this season (same lifetime restriction
                # class as a voluntary release).
                self.eligibility.record_release_block(giver[leg.side], leg.player_id)
            else:
                self.managers.adjust_balance(
                    giver[leg.side], -leg.cash_amount,
                    reason=f"trade {trade_id} cash out")
                self.managers.adjust_balance(
                    recipient[leg.side], leg.cash_amount,
                    reason=f"trade {trade_id} cash in")
        repo.set_status(trade_id, TradeStatus.ACCEPTED, resolved_at=at)

    def reject(self, trade_id: int, at: datetime) -> None:
        repo = self._require_repo()
        trade = repo.get(trade_id)
        if trade is None:
            raise TransferError(f"trade {trade_id} not found")
        if trade.status is not TradeStatus.PROPOSED:
            raise TransferError(f"trade {trade_id} is {trade.status.value}, not PROPOSED")
        repo.set_status(trade_id, TradeStatus.REJECTED, resolved_at=at)

    def cancel(self, trade_id: int, at: datetime) -> None:
        """Initiator withdraws their own proposal."""
        repo = self._require_repo()
        trade = repo.get(trade_id)
        if trade is None:
            raise TransferError(f"trade {trade_id} not found")
        if trade.status is not TradeStatus.PROPOSED:
            raise TransferError(f"trade {trade_id} is {trade.status.value}, not PROPOSED")
        repo.set_status(trade_id, TradeStatus.CANCELLED, resolved_at=at)

    def expire_window_close(self, window_id: int) -> int:
        """Auto-mark all PROPOSED trades in the window as EXPIRED at close."""
        repo = self._require_repo()
        count = 0
        for trade in repo.proposed_in_window(window_id):
            repo.set_status(trade.id, TradeStatus.EXPIRED, resolved_at=None)
            count += 1
        return count
