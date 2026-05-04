"""Player release (rule 八).

Always allowed; no cash refunded; releaser permanently loses signing
eligibility for that player this season unless reverted within 15 min.
"""

from __future__ import annotations

from datetime import datetime

from ...core.config import GameRules
from ...persistence.repositories import ManagerRepo
from ..eligibility import EligibilityService


class ReleaseService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        eligibility: EligibilityService,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.eligibility = eligibility

    def propose(self, manager_id: int, player_id: int, posted_at: datetime) -> int:
        """Insert Release row, mark RosterEntry pending; effective after
        revoke window expires.

        Note rule 八.5: revocation is invalidated if another manager has
        already signed the player during the revoke window. The committer
        in commit_due() detects this case.
        """
        raise NotImplementedError("TODO")

    def revoke(self, release_id: int, at: datetime) -> None:
        raise NotImplementedError(
            "TODO: enforce 15-min window AND check player still uncontested"
        )

    def commit_due(self, at: datetime) -> int:
        """Mark effective=True for Releases past revoke window. Adds
        RELEASED_LIFETIME eligibility record.
        """
        raise NotImplementedError("TODO")
