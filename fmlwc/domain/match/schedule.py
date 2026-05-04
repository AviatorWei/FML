"""Schedule generation: group-stage round robin + knockout bracket.

Bracket layout for `match.knockout.bracket = "euro2024_8team"` (rule 六.1):

    QF1: A1 vs B2     QF2: C1 vs D2
    QF3: B1 vs A2     QF4: D1 vs C2
    SF1: QF1 vs QF2   SF2: QF3 vs QF4
    F:   SF1 vs SF2
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from ...core.config import GameRules


@dataclass(frozen=True)
class FixtureSpec:
    home_manager_id: int
    away_manager_id: int
    group_letter: str | None = None
    bracket_slot: str | None = None


# === Group stage ===========================================================

class PairingStrategy(ABC):
    @abstractmethod
    def round_robin(self, group_managers: Sequence[int]) -> list[list[FixtureSpec]]: ...


class CircleMethodPairing(PairingStrategy):
    """Standard round-robin via the circle method."""

    def round_robin(self, group_managers):
        managers = list(group_managers)
        if len(managers) < 2:
            return []
        # Circle method needs even count; add a "bye" if odd.
        bye_added = False
        if len(managers) % 2 == 1:
            managers.append(None)
            bye_added = True
        n = len(managers)
        rounds = []
        # Fix first manager, rotate rest.
        fixed = managers[0]
        rotating = managers[1:]
        for r in range(n - 1):
            half1 = [fixed] + rotating[:n // 2 - 1]
            half2 = list(reversed(rotating[n // 2 - 1:]))
            round_fixtures = []
            for a, b in zip(half1, half2):
                if a is None or b is None:
                    continue
                # Alternate home/away by round index
                if r % 2 == 0:
                    round_fixtures.append(FixtureSpec(a, b))
                else:
                    round_fixtures.append(FixtureSpec(b, a))
            rounds.append(round_fixtures)
            rotating = [rotating[-1]] + rotating[:-1]
        return rounds


# === Bracket ===============================================================

_BRACKETS = {
    # Returns list of (home_group_letter, home_seed, away_group_letter, away_seed, slot_label)
    "euro2024_8team": [
        ("A", 1, "B", 2, "QF1"),
        ("C", 1, "D", 2, "QF2"),
        ("B", 1, "A", 2, "QF3"),
        ("D", 1, "C", 2, "QF4"),
    ],
}


class BracketBuilder:
    def __init__(self, rules: GameRules) -> None:
        self.rules = rules

    def quarterfinals(self, standings_by_group):
        """standings_by_group[g][0] = group winner, [1] = runner-up."""
        layout = _BRACKETS.get(self.rules.match.knockout.bracket)
        if layout is None:
            raise ValueError(f"unknown bracket: {self.rules.match.knockout.bracket}")
        out = []
        for hg, hs, ag, as_, slot in layout:
            home = standings_by_group[hg][hs - 1]
            away = standings_by_group[ag][as_ - 1]
            out.append(FixtureSpec(home, away, bracket_slot=slot))
        return out

    def next_round(self, prev_round_winners):
        """Pair up winners 1v2, 3v4, ..."""
        out = []
        for i in range(0, len(prev_round_winners), 2):
            if i + 1 >= len(prev_round_winners):
                break
            out.append(FixtureSpec(
                prev_round_winners[i], prev_round_winners[i + 1],
                bracket_slot=f"R{i // 2 + 1}",
            ))
        return out


# === Top-level scheduler ===================================================

class Scheduler:
    def __init__(self, rules: GameRules, pairing: PairingStrategy | None = None,
                 seed: int | None = None) -> None:
        self.rules = rules
        self.pairing = pairing or CircleMethodPairing()
        self.bracket = BracketBuilder(rules)
        self._rng = random.Random(seed)

    def draw_groups(self, manager_ids):
        """Random draw of N managers into G groups of equal size."""
        n = len(manager_ids)
        g = self.rules.managers.groups
        if n % g != 0:
            raise ValueError(f"can't split {n} managers into {g} equal groups")
        size = n // g
        ids = list(manager_ids)
        self._rng.shuffle(ids)
        groups = {}
        for i in range(g):
            letter = chr(ord("A") + i)
            groups[letter] = ids[i * size:(i + 1) * size]
        return groups

    def group_stage_fixtures(self, groups):
        """Return one list per gameweek across all groups.

        Each group plays its own round-robin in parallel.
        """
        per_group = {g: self.pairing.round_robin(ms) for g, ms in groups.items()}
        rounds = max((len(v) for v in per_group.values()), default=0)
        out = []
        for r in range(rounds):
            week = []
            for g, rounds_for_g in per_group.items():
                if r < len(rounds_for_g):
                    for fix in rounds_for_g[r]:
                        week.append(FixtureSpec(
                            fix.home_manager_id, fix.away_manager_id, group_letter=g
                        ))
            out.append(week)
        return out
