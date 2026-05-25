"""Admin dismissal of a player from a manager's roster.

Unlike voluntary Release (rule 八), a dismissal is:
  * Triggered by a league admin, not the manager.
  * Immediate — no 15-minute revoke window.
  * Still counts as team history: ManagerPlayerAthletics rows are kept
    intact, so career-stat breakdowns reflect the dismissed player's
    contributions during their time on the team.
  * Permanently blocks the dismissing manager from re-signing the player
    (DISMISSED_LIFETIME eligibility restriction), just as a voluntary
    release would under rule 八.4.
"""

from __future__ import annotations

from datetime import datetime

from ...core.config import GameRules
from ...persistence.repositories import DismissalRepo, ManagerRepo
from ..eligibility import EligibilityService


class DismissService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        dismissals: DismissalRepo,
        eligibility: EligibilityService,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.dismissals = dismissals
        self.eligibility = eligibility

    def dismiss(
        self,
        manager_id: int,
        player_id: int,
        at: datetime,
        *,
        reason: str | None = None,
    ) -> int:
        """Remove *player_id* from *manager_id*'s roster immediately.

        Steps
        -----
        1. Verify the player is on the manager's active roster
           (``release_from_roster`` raises ``KeyError`` if not).
        2. Set ``RosterEntry.released_at`` so the player appears as a
           free agent in ``query_player_list``.
        3. Add a ``DISMISSED_LIFETIME`` eligibility block so the manager
           cannot re-sign the player later this season.
        4. Persist a ``Dismissal`` audit record and return its id.

        Returns
        -------
        int
            The new ``Dismissal.id`` (audit record).

        Raises
        ------
        KeyError
            If *player_id* is not on an active roster entry for *manager_id*.
        """
        # Step 1 + 2: atomically clears the active roster entry.
        self.managers.release_from_roster(manager_id, player_id, at)

        # Step 3: lifetime re-signing block for this manager.
        self.eligibility.record_dismiss_block(manager_id, player_id)

        # Step 4: audit trail.
        return self.dismissals.create(manager_id, player_id, at, reason)
