"""Default lineup strategies (rule 四.8).

Two built-in strategies:
    previous_round            — copy last gameweek's accepted lineup
    top_value                 — pick highest market_value players per slot
    previous_round_then_top_value — fall back to top_value on round 1
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...core.config import GameRules
from ...persistence.repositories import ManagerRepo, PlayerRepo
from .validator import StarterInput


class LineupDefaultStrategy(ABC):
    @abstractmethod
    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]: ...


class PreviousRoundStrategy(LineupDefaultStrategy):
    def __init__(self, players: PlayerRepo, managers: ManagerRepo) -> None:
        self.players = players
        self.managers = managers

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        raise NotImplementedError(
            "TODO: SELECT lineups WHERE gw=gameweek_index-1 AND manager=manager_id"
        )


class TopValueStrategy(LineupDefaultStrategy):
    """Pick top market_value players for each slot, respecting position caps."""

    def __init__(self, rules: GameRules, players: PlayerRepo, managers: ManagerRepo) -> None:
        self.rules = rules
        self.players = players
        self.managers = managers

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        raise NotImplementedError("TODO")


class PreviousThenTopValue(LineupDefaultStrategy):
    """Default per FME-2021: previous round's lineup; round 1 → top value."""

    def __init__(self, prev: PreviousRoundStrategy, top: TopValueStrategy) -> None:
        self.prev = prev
        self.top = top

    def fill(self, manager_id: int, gameweek_index: int) -> list[StarterInput]:
        if gameweek_index <= 1:
            return self.top.fill(manager_id, gameweek_index)
        return self.prev.fill(manager_id, gameweek_index)


def get_default_strategy(
    name: str, rules: GameRules, players: PlayerRepo, managers: ManagerRepo
) -> LineupDefaultStrategy:
    prev = PreviousRoundStrategy(players, managers)
    top = TopValueStrategy(rules, players, managers)
    if name == "previous_round_then_top_value":
        return PreviousThenTopValue(prev, top)
    if name == "previous_round":
        return prev
    if name == "top_value":
        return top
    raise ValueError(f"unknown lineup default strategy: {name}")
