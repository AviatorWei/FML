"""Injury exception (rule 九).

When UEFA / a national federation officially removes a real player from
their Euro squad, this service:
    1. Refunds the most recent signing/trade fee paid for that player to
       their current owner.
    2. If removal happens after a free-sign window, grants the owner an
       extra free-sign opportunity until the next transfer window opens.
    3. If the removed player was a GK and the owner has zero balance and
       no other GK, additionally grants `gk_zero_balance_grant` cash.
"""

from __future__ import annotations

from datetime import datetime

from ..core.config import GameRules
from ..persistence.repositories import ManagerRepo


class InjuryAdjustmentService:
    def __init__(self, rules: GameRules, managers: ManagerRepo) -> None:
        self.rules = rules
        self.managers = managers

    def process(self, real_player_id: int, removed_at: datetime) -> None:
        """Single entry point.

        Steps:
            * find current owner (RosterEntry without released_at)
            * find latest acquired_price for that player
            * refund balance
            * if past free-sign window, register a one-off free-sign grant
              flag valid until next window opens
            * GK-zero-balance edge case
        """
        raise NotImplementedError("TODO")
