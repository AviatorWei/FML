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
from ...persistence.repositories import ManagerRepo, PlayerRepo
from ..eligibility import EligibilityService


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
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.eligibility = eligibility

    def propose(
        self,
        initiator_id: int,
        counterparty_id: int,
        legs: Sequence[TradeLegInput],
        proposed_at: datetime,
    ) -> int:
        """Persist Trade in PROPOSED state. No state change to either roster
        until accept().

        Pre-checks: legs well-formed, initiator owns the players they offer.
        """
        raise NotImplementedError("TODO")

    def accept(self, trade_id: int, at: datetime) -> None:
        """Atomic swap. All-or-nothing. Re-runs eligibility + balance checks
        on both sides at acceptance time (situations may have changed since
        proposal).
        """
        raise NotImplementedError(
            "TODO: in single tx — verify ownership, eligibility, balances; "
            "move RosterEntry rows; adjust balances; status -> ACCEPTED"
        )

    def reject(self, trade_id: int, at: datetime) -> None:
        raise NotImplementedError("TODO")

    def expire_window_close(self, window_id: int) -> int:
        """Auto-mark all PROPOSED trades as EXPIRED at window close."""
        raise NotImplementedError("TODO")
