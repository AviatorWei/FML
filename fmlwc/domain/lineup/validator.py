"""Lineup validation per rule 四.

Rules:
    * 8 <= |starters| <= 10
    * appearance caps: G <= 1, D <= 3, M <= 4, F <= 2 (slot positions)
    * must_have: at least 1 G slot
    * a player whose actual position != slot is allowed only via backward
      substitution (D->M/F, M->F).  Misplaced players are silently
      dropped from the effective lineup (rule 四.9), no penalty.
    * the player must be on the manager's roster.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.config import GameRules
from ...core.enums import Position
from ...core.exceptions import LineupError


@dataclass(frozen=True)
class StarterInput:
    player_id: int
    slot_position: Position


@dataclass(frozen=True)
class DroppedStarter:
    player_id: int
    reason: str


@dataclass(frozen=True)
class ValidatedLineup:
    accepted: list[StarterInput]
    dropped: list[DroppedStarter]


class LineupValidator:
    def __init__(self, rules: GameRules, players, managers) -> None:
        self.rules = rules
        self.players = players
        self.managers = managers

    def validate(self, manager_id: int, starters: list[StarterInput]) -> ValidatedLineup:
        cfg = self.rules.lineup
        roster_player_ids = {e.player_id for e in self.managers.list_roster(manager_id)}

        accepted: list[StarterInput] = []
        dropped: list[DroppedStarter] = []
        seen_player: set[int] = set()

        for s in starters:
            if s.player_id in seen_player:
                dropped.append(DroppedStarter(s.player_id, "duplicate in lineup"))
                continue
            seen_player.add(s.player_id)

            if s.player_id not in roster_player_ids:
                dropped.append(DroppedStarter(s.player_id, "not on roster"))
                continue

            actual = self.players.get(s.player_id).position
            if actual is s.slot_position:
                accepted.append(s)
                continue

            # backward substitution per rules.lineup.backward_substitution
            allowed = cfg.backward_substitution.get(actual, [])
            if s.slot_position in allowed:
                accepted.append(s)
            else:
                # Rule 四.9: silently drop misplaced player, no penalty
                dropped.append(
                    DroppedStarter(s.player_id, f"misplaced ({actual.value} -> {s.slot_position.value})")
                )

        # appearance caps
        per_pos_count: dict[Position, int] = {p: 0 for p in Position}
        for s in accepted:
            per_pos_count[s.slot_position] += 1

        for pos, cap in cfg.appearance_caps.items():
            if per_pos_count[pos] > cap:
                raise LineupError(
                    f"appearance cap exceeded: {pos.value} has {per_pos_count[pos]} > {cap}"
                )

        # size bounds
        if len(accepted) < cfg.starters_min:
            raise LineupError(
                f"too few starters: {len(accepted)} < {cfg.starters_min}"
            )
        if len(accepted) > cfg.starters_max:
            raise LineupError(
                f"too many starters: {len(accepted)} > {cfg.starters_max}"
            )

        # must_have positions
        for required in cfg.must_have_positions:
            if per_pos_count[required] < 1:
                raise LineupError(
                    f"must include at least one {required.value}"
                )

        return ValidatedLineup(accepted=accepted, dropped=dropped)
