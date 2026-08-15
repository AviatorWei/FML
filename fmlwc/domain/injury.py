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

from dataclasses import dataclass
from datetime import datetime

from ..core.config import GameRules
from ..core.enums import Position
from ..core.exceptions import TransferError
from ..persistence.repositories import (
    InjuryRepo,
    ManagerRepo,
    PlayerRepo,
    TransferRepo,
)


@dataclass(frozen=True)
class InjuryOutcome:
    """What the adjustment did — returned so callers/UIs can report it."""
    owner_manager_id: int | None
    refund: int
    free_sign_grant: bool
    gk_grant: int
    adjustment_id: int | None


class InjuryAdjustmentService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo | None = None,
        transfers: TransferRepo | None = None,
        injuries: InjuryRepo | None = None,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.transfers = transfers
        self.injuries = injuries

    def process(self, real_player_id: int, removed_at: datetime) -> InjuryOutcome:
        """Single entry point.

        Steps:
            * find current owner (RosterEntry without released_at)
            * find latest acquired_price for that player
            * release + refund balance (if rules.injury.refund_last_signing_fee)
            * if removal falls outside any open free-sign window, register a
              one-off free-sign grant flag (rule 九.2)
            * GK-zero-balance edge case (rule 九.3)
        """
        if not self.rules.injury.enabled:
            raise TransferError("injury adjustments are disabled by rules")

        # -- find current owner + latest price -------------------------------
        owner_id: int | None = None
        entry = None
        for mgr in self.managers.list_active():
            for e in self.managers.list_roster(mgr.id):
                if e.player_id == real_player_id:
                    owner_id, entry = mgr.id, e
                    break
            if owner_id is not None:
                break

        refund = 0
        gk_grant = 0
        free_sign_grant = False

        if owner_id is not None and entry is not None:
            self.managers.release_from_roster(owner_id, real_player_id, removed_at)

            if self.rules.injury.refund_last_signing_fee and entry.acquired_price:
                refund = entry.acquired_price
                self.managers.adjust_balance(
                    owner_id, refund,
                    reason=f"injury refund player {real_player_id}",
                )

            # -- rule 九.2: extra free sign if outside an open window --------
            if self.rules.injury.grant_extra_free_sign_after_window:
                in_window = (
                    self.transfers is not None
                    and self.transfers.current_window(removed_at) is not None
                )
                free_sign_grant = not in_window

            # -- rule 九.3: GK zero-balance grant ------------------------------
            if self.players is not None:
                player = self.players.get(real_player_id)
                if player is not None and player.position is Position.G:
                    owner = self.managers.get(owner_id)
                    has_other_gk = (
                        self.managers.position_count(owner_id, Position.G) > 0
                    )
                    if owner.balance == 0 and not has_other_gk:
                        gk_grant = self.rules.injury.gk_zero_balance_grant
                        if gk_grant:
                            self.managers.adjust_balance(
                                owner_id, gk_grant,
                                reason=f"injury GK zero-balance grant "
                                       f"(player {real_player_id})",
                            )

        adjustment_id = None
        if self.injuries is not None:
            adjustment_id = self.injuries.create(
                real_player_id=real_player_id,
                removed_at=removed_at,
                refund_amount=refund,
                free_sign_grant=free_sign_grant,
                granted_to_manager_id=owner_id if free_sign_grant else None,
            )

        return InjuryOutcome(
            owner_manager_id=owner_id,
            refund=refund,
            free_sign_grant=free_sign_grant,
            gk_grant=gk_grant,
            adjustment_id=adjustment_id,
        )
