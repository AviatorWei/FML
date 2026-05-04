"""Knockout-winner pick (rule 六.6).

Each match's winner gets to pick one player from the loser's
**pre-match** roster (snapshotted in `roster_snapshots`). No fee. Must
clear EligibilityService.
"""

from __future__ import annotations

from datetime import datetime

from ...core.config import GameRules
from ...persistence.repositories import ManagerRepo, PlayerRepo
from ..eligibility import EligibilityService


class PickService:
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

    def take_snapshot(self, manager_id: int, fixture_id: int, taken_at: datetime) -> int:
        """Persist roster snapshot at start of knockout match."""
        raise NotImplementedError("TODO")

    def pick(
        self,
        knockout_fixture_id: int,
        picker_manager_id: int,
        picked_player_id: int,
        at: datetime,
    ) -> None:
        """Validate picker won the fixture; verify player was on opponent's
        snapshot; eligibility check; transfer player to picker (no fee).
        """
        raise NotImplementedError("TODO")

    def expire_unpicked(self, fixture_id: int, deadline: datetime) -> None:
        """Mark unused pick rights as forfeited after rules.match.knockout.pick_deadline_seconds."""
        raise NotImplementedError("TODO")
