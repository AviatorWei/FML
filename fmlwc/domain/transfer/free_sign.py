"""Free signing (rule 三).

Lifecycle:
    propose ---posted_at---> [pending, may be revoked within 15 min]
            ---revoke_window expires--> effective=True; balance -= 10m
"""

from __future__ import annotations

from datetime import datetime

from ...core.config import GameRules
from ...persistence.repositories import ManagerRepo, PlayerRepo, TransferRepo
from ..eligibility import EligibilityService


class FreeSignService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        transfers: TransferRepo,
        eligibility: EligibilityService,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.transfers = transfers
        self.eligibility = eligibility

    # -- public API --------------------------------------------------------
    def propose(self, manager_id: int, player_id: int, posted_at: datetime) -> int:
        """Validate (rule 三.3) + persist FreeSign row, status pending.

        Validations:
            * window currently open at posted_at
            * player is free agent
            * roster total < cap
            * balance >= 10m
            * eligibility allowed (defers to EligibilityService — covers
              cooldown 三.6 and 三.7 via eligibility records)

        Returns free_sign_id.
        """
        raise NotImplementedError("TODO")

    def revoke(self, free_sign_id: int, at: datetime) -> None:
        """Within 15 min of posted_at — mark revoked=True, no charge."""
        raise NotImplementedError(
            "TODO: enforce at - posted_at <= rules.transfer.revoke_window_seconds"
        )

    def commit_due(self, at: datetime) -> int:
        """Apply effective=True for FreeSigns whose revoke window has passed.

        Returns count committed. Charges fee, inserts RosterEntry, records
        FREE_SIGN_SAME_WINDOW eligibility block for other managers.
        """
        raise NotImplementedError("TODO")

    # -- internal ----------------------------------------------------------
    def _within_cooldown(self, manager_id: int, posted_at: datetime) -> bool:
        """Rule 三.6: only one effective free sign per natural period."""
        raise NotImplementedError(
            "TODO: query last effective free sign by this manager; "
            "compare with rules.transfer.windows[i].free_sign_period_seconds"
        )
