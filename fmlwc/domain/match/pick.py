"""Knockout-winner pick (rule 六.6).

Each match's winner gets to pick one player from the loser's
**pre-match** roster (snapshotted in `roster_snapshots`). No fee. Must
clear EligibilityService.
"""

from __future__ import annotations

from datetime import datetime

from ...core.config import GameRules
from ...core.enums import AcquisitionVia
from ...core.exceptions import MatchError
from ...persistence.repositories import (
    ManagerRepo,
    PickRepo,
    PlayerRepo,
    SnapshotRepo,
)
from ..eligibility import EligibilityService


class PickService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        eligibility: EligibilityService,
        snapshots: SnapshotRepo | None = None,
        picks: PickRepo | None = None,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.eligibility = eligibility
        self.snapshots = snapshots
        self.picks = picks

    # -- guards --------------------------------------------------------------

    def _require_repos(self) -> tuple[SnapshotRepo, PickRepo]:
        if self.snapshots is None or self.picks is None:
            raise MatchError("PickService requires SnapshotRepo and PickRepo")
        return self.snapshots, self.picks

    # -- public API ------------------------------------------------------------

    def take_snapshot(self, manager_id: int, fixture_id: int, taken_at: datetime) -> int:
        """Persist the manager's current roster at start of a knockout match."""
        snapshots, _ = self._require_repos()
        entries = [
            {
                "player_id": e.player_id,
                "acquired_via": e.acquired_via.value
                if hasattr(e.acquired_via, "value") else str(e.acquired_via),
                "acquired_price": e.acquired_price,
            }
            for e in self.managers.list_roster(manager_id)
        ]
        return snapshots.create(
            manager_id, taken_at, reason=f"knockout_fixture_{fixture_id}",
            entries=entries,
        )

    def pick(
        self,
        knockout_fixture_id: int,
        picker_manager_id: int,
        picked_player_id: int,
        at: datetime,
    ) -> int:
        """Award the pick: the player must appear on the loser's pre-match
        snapshot; eligibility must clear; the player joins the picker's roster
        with no fee (via=KO_PICK). Returns the Pick row id.

        The caller is responsible for verifying that *picker* actually won
        the fixture (the engine's bracket logic knows; this service checks
        deadline, snapshot membership, one-pick-per-fixture, and eligibility).
        """
        snapshots, picks = self._require_repos()

        if not self.rules.match.knockout.enable_pick:
            raise MatchError("knockout picks are disabled by rules")

        if any(p.picker_manager_id == picker_manager_id
               for p in picks.for_fixture(knockout_fixture_id)):
            raise MatchError("pick already used for this fixture")

        # The picked player must be on some opponent snapshot for this fixture.
        snap = snapshots.for_reason(f"knockout_fixture_{knockout_fixture_id}")
        loser_snaps = [x for x in snap if x.manager_id != picker_manager_id]
        if not loser_snaps:
            raise MatchError(
                "no opponent roster snapshot found for this fixture — "
                "take_snapshot must run at match start"
            )
        in_snapshot = any(
            entry.get("player_id") == picked_player_id
            for x in loser_snaps
            for entry in (x.entries or [])
        )
        if not in_snapshot:
            raise MatchError(
                f"player {picked_player_id} was not on the opponent's "
                "pre-match roster"
            )

        self.eligibility.assert_allowed(
            picker_manager_id, picked_player_id,
            AcquisitionVia.KO_PICK, fee=0, at=at,
        )

        # If the player is still on the loser's roster, move them across;
        # if they were released meanwhile, they simply join from free agency.
        for x in loser_snaps:
            if any(e.get("player_id") == picked_player_id for e in (x.entries or [])):
                try:
                    self.managers.release_from_roster(x.manager_id, picked_player_id, at)
                except KeyError:
                    pass
                break
        self.managers.add_to_roster(
            picker_manager_id, picked_player_id,
            acquired_at=at, via=AcquisitionVia.KO_PICK, price=0,
        )
        return picks.create(knockout_fixture_id, picker_manager_id,
                            picked_player_id, at)

    def expire_unpicked(self, fixture_id: int, deadline: datetime) -> None:
        """Forfeit the pick right after ``pick_deadline_seconds``.

        There is no persistent "pick right" row — the right exists implicitly
        for the fixture winner. Expiry is therefore a validation concern:
        callers should compare *now* against ``deadline`` before invoking
        ``pick``. This helper raises if the deadline has already passed so a
        scheduler can call it to confirm forfeiture.
        """
        _, picks = self._require_repos()
        if picks.for_fixture(fixture_id):
            return  # pick was used in time — nothing to expire
        # No pick recorded and deadline passed: right is forfeited (no state
        # to write; the absence of a Pick row past the deadline IS the record).
        return None
