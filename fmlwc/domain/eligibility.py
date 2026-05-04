"""Single chokepoint for "may manager X sign player Y at time T?".

All four signing pathways (auction, free sign, trade, knockout pick) call
`EligibilityService.check` before mutating state. Centralises rules
RULES.md 二.7, 三.7, 八.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..core.config import GameRules
from ..core.enums import AcquisitionVia, EligibilityRestriction, Position
from ..core.exceptions import EligibilityError


@dataclass(frozen=True)
class EligibilityVerdict:
    allowed: bool
    reason: str | None = None

    @classmethod
    def ok(cls):
        return cls(True, None)

    @classmethod
    def deny(cls, reason: str):
        return cls(False, reason)


class EligibilityService:
    def __init__(self, rules: GameRules, managers, players, eligibility) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.eligibility = eligibility

    def check(
        self,
        manager_id: int,
        player_id: int,
        via: AcquisitionVia,
        fee: int,
        at: datetime,
    ) -> EligibilityVerdict:
        # Cheap checks first.
        # 1. Total roster cap
        roster = self.managers.list_roster(manager_id)
        if len(roster) >= self.rules.roster.total_cap:
            return EligibilityVerdict.deny(
                f"roster full ({len(roster)} >= {self.rules.roster.total_cap})"
            )

        # 2. Position cap
        player = self.players.get(player_id)
        pos = player.position
        cap = self.rules.roster.position_caps.get(pos, 0)
        cur = self.managers.position_count(manager_id, pos)
        if cur >= cap:
            return EligibilityVerdict.deny(
                f"position {pos.value} cap reached ({cur} >= {cap})"
            )

        # 3. Balance
        # KO_PICK and INJURY_GRANT are free; auction handles its own balance check
        # at bid time (rule 二.3.(2)). For free sign and trade we require it.
        if via in (AcquisitionVia.FREE_SIGN, AcquisitionVia.TRADE):
            mgr = self.managers.get(manager_id)
            if mgr.balance < fee:
                return EligibilityVerdict.deny(
                    f"insufficient balance ({mgr.balance} < {fee})"
                )

        # 4. Active eligibility records
        records = self.eligibility.list_for_player(player_id, at)
        for rec in records:
            t = rec.restriction_type
            if t in (EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
                     EligibilityRestriction.FREE_SIGN_SAME_WINDOW,
                     EligibilityRestriction.KNOCKOUT_PICK_BLACKLIST):
                # These restrictions name the WINNER; others are blocked.
                if rec.manager_id != manager_id:
                    return EligibilityVerdict.deny(
                        f"blocked by {t.value} (player owned/won by manager {rec.manager_id})"
                    )
            elif t is EligibilityRestriction.RELEASED_LIFETIME:
                if rec.manager_id == manager_id:
                    return EligibilityVerdict.deny(
                        f"blocked by {t.value} (you released this player)"
                    )
        return EligibilityVerdict.ok()

    def assert_allowed(self, manager_id, player_id, via, fee, at):
        v = self.check(manager_id, player_id, via, fee, at)
        if not v.allowed:
            raise EligibilityError(v.reason or "ineligible")

    # --- write-side helpers (called by services after a signing) ----------

    def record_auction_block(
        self, except_winner_id: int, player_id: int, next_window_until: datetime
    ) -> None:
        """Rule 二.7: every OTHER manager loses eligibility until
        `next_window_until` (typically the close of the next transfer window).
        We tag the WINNER as the bearer so .check() can identify the holder.
        """
        self.eligibility.add(
            manager_id=except_winner_id,
            player_id=player_id,
            restriction=EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
            valid_until=next_window_until,
            reason="auction won — others blocked next window",
        )

    def record_free_sign_block(
        self, except_signer_id: int, player_id: int, window_close: datetime
    ) -> None:
        """Rule 三.7: same-window block for everyone except the signer."""
        self.eligibility.add(
            manager_id=except_signer_id,
            player_id=player_id,
            restriction=EligibilityRestriction.FREE_SIGN_SAME_WINDOW,
            valid_until=window_close,
            reason="free sign — others blocked this window",
        )

    def record_release_block(self, manager_id: int, player_id: int) -> None:
        """Rule 八.4: releaser permanently loses eligibility this season."""
        self.eligibility.add(
            manager_id=manager_id,
            player_id=player_id,
            restriction=EligibilityRestriction.RELEASED_LIFETIME,
            valid_until=None,
            reason="self-release lifetime block",
        )
