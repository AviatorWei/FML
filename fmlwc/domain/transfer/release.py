"""Player release (rule 八).

Always allowed; refund per ``rules.release.refund`` (0 in FME-2021); the
releaser permanently loses signing eligibility for that player this season
(rule 八.4) unless the release is reverted within the revoke window.

Lifecycle of a Release row (mirrors FreeSignService):
    propose()    →  revoked=False, effective=False   (pending; player stays
                    on the roster so the release can still be reverted)
    revoke()     →  revoked=True                     (cancelled, no change)
    commit_due() →  effective=True                   (roster entry closed,
                    refund credited, RELEASED_LIFETIME block recorded)
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...core.config import GameRules
from ...core.exceptions import TransferError
from ...persistence.repositories import ManagerRepo, ReleaseRepo
from ..eligibility import EligibilityService


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _elapsed_seconds(later: datetime, earlier: datetime) -> float:
    return (_naive_utc(later) - _naive_utc(earlier)).total_seconds()


class ReleaseService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        eligibility: EligibilityService,
        releases: ReleaseRepo | None = None,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.eligibility = eligibility
        self.releases = releases

    # -- guards ---------------------------------------------------------------

    def _require_repo(self) -> ReleaseRepo:
        if self.releases is None:
            raise TransferError("ReleaseService requires a ReleaseRepo")
        return self.releases

    # -- public API -------------------------------------------------------------

    def propose(self, manager_id: int, player_id: int, posted_at: datetime) -> int:
        """Insert a pending Release row; the roster entry is untouched until
        ``commit_due`` so the release can be reverted within the window.

        Raises ``TransferError`` if the player is not on the manager's active
        roster or a pending release for the same player already exists.
        """
        repo = self._require_repo()

        on_roster = any(
            e.player_id == player_id for e in self.managers.list_roster(manager_id)
        )
        if not on_roster:
            raise TransferError(
                f"player {player_id} is not on manager {manager_id}'s active roster"
            )

        for r in repo.pending_for_manager(manager_id):
            if r.player_id == player_id:
                raise TransferError(
                    f"a pending release for player {player_id} already exists"
                )

        return repo.create(manager_id, player_id, posted_at)

    def revoke(self, release_id: int, at: datetime) -> None:
        """Cancel a pending release within ``rules.release.revoke_window_seconds``.

        Rule 八.5: revocation is invalidated if the player has already been
        contested. Because the roster entry stays active until commit, the
        player cannot be signed by anyone during the window, so the only
        checks needed here are state + clock.
        """
        repo = self._require_repo()
        rel = repo.get(release_id)
        if rel is None:
            raise TransferError(f"release {release_id} not found")
        if rel.revoked:
            raise TransferError(f"release {release_id} is already revoked")
        if rel.effective:
            raise TransferError(
                f"release {release_id} is already effective and cannot be revoked"
            )
        elapsed = _elapsed_seconds(at, rel.posted_at)
        limit = self.rules.release.revoke_window_seconds
        if elapsed > limit:
            raise TransferError(
                f"revoke window expired: {elapsed:.0f}s elapsed, limit is {limit}s"
            )
        repo.mark_revoked(release_id)

    def commit_due(self, at: datetime) -> int:
        """Commit all pending releases whose revoke window has elapsed.

        For each: close the roster entry, credit ``rules.release.refund``,
        record the RELEASED_LIFETIME block (rule 八.4) if enabled, and mark
        the release effective. Returns the number committed.
        """
        repo = self._require_repo()
        committed = 0
        for rel in repo.pending():
            if _elapsed_seconds(at, rel.posted_at) <= self.rules.release.revoke_window_seconds:
                continue
            try:
                self.managers.release_from_roster(rel.manager_id, rel.player_id, at)
            except KeyError:
                # Player already left the roster some other way (dismissal,
                # trade); void the release rather than double-processing.
                repo.mark_revoked(rel.id)
                continue
            if self.rules.release.refund:
                self.managers.adjust_balance(
                    rel.manager_id, self.rules.release.refund,
                    reason=f"release refund player {rel.player_id}",
                )
            if self.rules.release.releaser_lifetime_block:
                self.eligibility.record_release_block(rel.manager_id, rel.player_id)
            repo.mark_effective(rel.id)
            committed += 1
        return committed

    # -- try_* wrappers -----------------------------------------------------------

    def try_propose(self, manager_id: int, player_id: int, posted_at: datetime):
        try:
            return True, self.propose(manager_id, player_id, posted_at), None
        except TransferError as exc:
            return False, None, str(exc)

    def try_revoke(self, release_id: int, at: datetime):
        try:
            self.revoke(release_id, at)
            return True, release_id, None
        except TransferError as exc:
            return False, None, str(exc)
