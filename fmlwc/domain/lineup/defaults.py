"""Default lineup strategies (rule 四.8).

Two built-in strategies:
    previous_round            — copy last gameweek's accepted lineup
    top_value                 — pick highest market_value players per slot
    previous_round_then_top_value — fall back to top_value on round 1
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from ...core.config import GameRules
from ...persistence.repositories import ManagerRepo, PlayerRepo
from .validator import StarterInput

# Injected by the persistence-aware caller: returns the starters the manager
# fielded in the given gameweek, or None when no lineup exists.
LineupLoader = Callable[[int, int], Optional[list[StarterInput]]]


class LineupDefaultStrategy(ABC):
    @abstractmethod
    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]: ...


class PreviousRoundStrategy(LineupDefaultStrategy):
    def __init__(
        self,
        players: PlayerRepo,
        managers: ManagerRepo,
        lineup_loader: LineupLoader | None = None,
    ) -> None:
        self.players = players
        self.managers = managers
        self.lineup_loader = lineup_loader

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        """Copy the previous gameweek's lineup, dropping any starters who have
        since left the roster. Returns [] when no previous lineup exists (or
        no loader is wired) — callers should fall back to TopValueStrategy."""
        if self.lineup_loader is None or gameweek_index <= 1:
            return []
        previous = self.lineup_loader(manager_id, gameweek_index - 1)
        if not previous:
            return []
        roster_ids = {e.player_id for e in self.managers.list_roster(manager_id)}
        return [s for s in previous if s.player_id in roster_ids]


class TopValueStrategy(LineupDefaultStrategy):
    """Pick top market_value players for each slot, respecting position caps."""

    def __init__(self, rules: GameRules, players: PlayerRepo, managers: ManagerRepo) -> None:
        self.rules = rules
        self.players = players
        self.managers = managers

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        cfg = self.rules.lineup
        roster_players = []
        for entry in self.managers.list_roster(manager_id):
            p = self.players.get(entry.player_id)
            if p is not None:
                roster_players.append(p)
        # Highest market value first; stable tiebreak by player id.
        roster_players.sort(
            key=lambda p: (-(getattr(p, "market_value", 0) or 0), p.id)
        )

        caps = dict(cfg.appearance_caps)
        counts = {pos: 0 for pos in caps}
        starters: list[StarterInput] = []

        # Pass 1 — guarantee must-have positions (≥1 of each, usually the GK).
        for pos in cfg.must_have_positions:
            best = next((p for p in roster_players if p.position is pos), None)
            if best is not None:
                starters.append(StarterInput(player_id=best.id, slot_position=pos))
                counts[pos] = counts.get(pos, 0) + 1

        chosen = {s.player_id for s in starters}

        # Pass 2 — fill remaining slots by value, native position only.
        for p in roster_players:
            if len(starters) >= cfg.starters_max:
                break
            if p.id in chosen:
                continue
            cap = caps.get(p.position, 0)
            if counts.get(p.position, 0) >= cap:
                continue
            starters.append(StarterInput(player_id=p.id, slot_position=p.position))
            counts[p.position] = counts.get(p.position, 0) + 1
            chosen.add(p.id)

        # Pass 3 — backward substitution to reach starters_min if possible:
        # unused D fill open M/F slots, unused M fill open F slots.
        if len(starters) < cfg.starters_min:
            for p in roster_players:
                if len(starters) >= cfg.starters_max:
                    break
                if p.id in chosen:
                    continue
                for slot in cfg.backward_substitution.get(p.position, []):
                    if counts.get(slot, 0) < caps.get(slot, 0):
                        starters.append(StarterInput(player_id=p.id, slot_position=slot))
                        counts[slot] = counts.get(slot, 0) + 1
                        chosen.add(p.id)
                        break

        return starters


class PreviousThenTopValue(LineupDefaultStrategy):
    """Default per FME-2021: previous round's lineup; round 1 → top value."""

    def __init__(self, prev: PreviousRoundStrategy, top: TopValueStrategy) -> None:
        self.prev = prev
        self.top = top

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        if gameweek_index <= 1:
            return self.top.fill(manager_id, gameweek_index)
        starters = self.prev.fill(manager_id, gameweek_index)
        return starters if starters else self.top.fill(manager_id, gameweek_index)


def get_default_strategy(
    name: str,
    rules: GameRules,
    players: PlayerRepo,
    managers: ManagerRepo,
    lineup_loader: LineupLoader | None = None,
) -> LineupDefaultStrategy:
    prev = PreviousRoundStrategy(players, managers, lineup_loader)
    top = TopValueStrategy(rules, players, managers)
    if name == "previous_round_then_top_value":
        return PreviousThenTopValue(prev, top)
    if name == "previous_round":
        return prev
    if name == "top_value":
        return top
    raise ValueError(f"unknown lineup default strategy: {name}")
