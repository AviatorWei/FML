"""Free signing service (rule 三).

Lifecycle of a FreeSign row
----------------------------
    propose()  →  revoked=False, effective=False  (pending)
    revoke()   →  revoked=True                    (cancelled, no charge)
    commit_due() → effective=True                 (roster updated, fee charged)

Call ``commit_due`` periodically (e.g. once per minute) or immediately after
the revoke window has elapsed for a given sign.

Public API
----------
Both ``propose`` and ``revoke`` raise ``TransferError`` / ``EligibilityError``
on failure.  The ``try_*`` wrappers catch those and return a ``FreeSignResult``
so web handlers can inspect the outcome without a try/except.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ...core.enums import AcquisitionVia
from ...core.exceptions import EligibilityError, TransferError
from ...core.config import GameRules
from ...persistence.repositories import (
    FreeSignRepo,
    ManagerRepo,
    PlayerRepo,
    TransferRepo,
)
from ..eligibility import EligibilityService


# ---------------------------------------------------------------------------
# Result type (returned by try_* methods; used by the interface layer)
# ---------------------------------------------------------------------------

@dataclass
class FreeSignResult:
    """Outcome of a propose or revoke call."""
    success: bool
    free_sign_id: int | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _naive_utc(dt: datetime) -> datetime:
    """Strip timezone info, converting to UTC first if needed."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _elapsed_seconds(later: datetime, earlier: datetime) -> float:
    return (_naive_utc(later) - _naive_utc(earlier)).total_seconds()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FreeSignService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        transfers: TransferRepo,
        free_signs: FreeSignRepo,
        eligibility: EligibilityService,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.transfers = transfers
        self.free_signs = free_signs
        self.eligibility = eligibility

    # -- public API (raising) -----------------------------------------------

    def propose(self, manager_id: int, player_id: int, posted_at: datetime) -> int:
        """Validate and persist a free-sign proposal.

        Checks (rule 三.3):
          1. Transfer window open at ``posted_at``
          2. Player is a free agent
          3. One-per-period cooldown (rule 三.6)
          4. Eligibility gate: roster cap, position cap, balance >= 10m,
             active restriction records (delegates to ``EligibilityService``)

        Returns the new ``free_sign_id``.
        Raises ``TransferError`` or ``EligibilityError`` on any violation.
        """
        window = self.transfers.current_window(posted_at)
        if window is None:
            raise TransferError("no transfer window open at this time")

        if not self.players.is_free_agent(player_id, posted_at):
            raise TransferError(
                f"player {player_id} is not a free agent at this time"
            )

        if self._within_cooldown(manager_id, window, posted_at):
            raise TransferError(
                "manager already has a free sign in the current cooldown period "
                f"({window.free_sign_period_seconds}s)"
            )

        self.eligibility.assert_allowed(
            manager_id,
            player_id,
            AcquisitionVia.FREE_SIGN,
            fee=self.rules.transfer.free_sign_fee,
            at=posted_at,
        )

        return self.free_signs.create(
            window_id=window.id,
            manager_id=manager_id,
            player_id=player_id,
            fee=self.rules.transfer.free_sign_fee,
            posted_at=posted_at,
        )

    def revoke(self, free_sign_id: int, at: datetime) -> None:
        """Cancel a pending free sign within the revoke window (rule 三.5).

        Raises ``TransferError`` if already revoked, already effective, or
        the revoke window (``rules.transfer.revoke_window_seconds``) has passed.
        """
        fs = self.free_signs.get(free_sign_id)

        if fs.revoked:
            raise TransferError(f"free sign {free_sign_id} is already revoked")
        if fs.effective:
            raise TransferError(
                f"free sign {free_sign_id} is already effective and cannot be revoked"
            )

        elapsed = _elapsed_seconds(at, fs.posted_at)
        limit = self.rules.transfer.revoke_window_seconds
        if elapsed > limit:
            raise TransferError(
                f"revoke window expired: {elapsed:.0f}s elapsed, limit is {limit}s"
            )

        self.free_signs.mark_revoked(free_sign_id)

    def commit_due(self, at: datetime) -> int:
        """Commit all pending free signs whose revoke window has elapsed.

        For each committed sign:
          - Deduct fee from manager's balance
          - Add player to manager's roster (via FREE_SIGN)
          - Record FREE_SIGN_SAME_WINDOW eligibility block for all other
            managers in the same window (rule 三.7), if enabled in rules
          - Mark sign as effective

        Returns the number of signs committed.
        Should be called periodically (e.g. once per minute) or triggered
        immediately after the revoke window expires.
        """
        window = self.transfers.current_window(at)
        if window is None:
            return 0

        pending = self.free_signs.pending_in_window(window.id)
        committed = 0

        for fs in pending:
            elapsed = _elapsed_seconds(at, fs.posted_at)
            if elapsed <= self.rules.transfer.revoke_window_seconds:
                continue  # still within revoke window

            self.managers.adjust_balance(
                fs.manager_id,
                -fs.fee,
                reason=f"free sign player {fs.player_id}",
            )
            self.managers.add_to_roster(
                fs.manager_id,
                fs.player_id,
                acquired_at=fs.posted_at,
                via=AcquisitionVia.FREE_SIGN,
                price=fs.fee,
            )

            if self.rules.transfer.same_window_block_after_free_sign:
                self.eligibility.record_free_sign_block(
                    except_signer_id=fs.manager_id,
                    player_id=fs.player_id,
                    window_close=window.closes_at,
                )

            self.free_signs.mark_effective(fs.id)
            committed += 1

        return committed

    # -- try_* wrappers (non-raising; for web/shell interface) ---------------

    def try_propose(
        self, manager_id: int, player_id: int, posted_at: datetime
    ) -> FreeSignResult:
        """Like ``propose`` but returns a ``FreeSignResult`` instead of raising."""
        try:
            fid = self.propose(manager_id, player_id, posted_at)
            return FreeSignResult(success=True, free_sign_id=fid)
        except (TransferError, EligibilityError) as exc:
            return FreeSignResult(success=False, error=str(exc))

    def try_revoke(self, free_sign_id: int, at: datetime) -> FreeSignResult:
        """Like ``revoke`` but returns a ``FreeSignResult`` instead of raising."""
        try:
            self.revoke(free_sign_id, at)
            return FreeSignResult(success=True, free_sign_id=free_sign_id)
        except TransferError as exc:
            return FreeSignResult(success=False, error=str(exc))

    # -- internal ------------------------------------------------------------

    def _within_cooldown(
        self, manager_id: int, window_obj, posted_at: datetime
    ) -> bool:
        """Rule 三.6: block if any non-revoked sign by this manager exists
        within the current cooldown period (window.free_sign_period_seconds).
        """
        period = window_obj.free_sign_period_seconds
        if period == 0:
            return False

        existing = self.free_signs.for_manager_in_window(manager_id, window_obj.id)
        for fs in existing:
            if fs.revoked:
                continue
            elapsed = _elapsed_seconds(posted_at, fs.posted_at)
            if 0 <= elapsed < period:
                return True
        return False
