"""Round (gameweek) lifecycle service.

Responsibilities:
    add_event    — record a player event while the gameweek is LIVE
    remove_event — retract a mistaken event while the gameweek is LIVE
    finalize_gameweek — lock the round, compute results + bonuses,
                        flush stats to PlayerAthletics and ManagerAthletics

Attribution flow (the DAL conversion):
    MatchEvent stores (gameweek_id, player_id) only.
    At finalize time, FixtureRepo.player_manager_map(gameweek_id) reads
    every Lineup in the gameweek and returns {player_id: manager_id},
    so events are attributed to the manager who fielded each player —
    not whoever owns them today.
"""

from __future__ import annotations

from ...core.config import GameRules
from ...core.enums import GameweekStatus, RealEventType
from ...core.exceptions import MatchError
from ...persistence.repositories import (
    AthleticsRepo,
    FixtureRepo,
    GameweekRepo,
    ManagerRepo,
    MatchEventRepo,
)
from .bonuses import BonusContext, BonusEngine
from .scoring import ValidGoalCalculator

# Mapping from RealEventType value to the athletics field it increments.
_EVENT_TO_FIELD: dict[str, str] = {
    RealEventType.GOAL.value: "goals",
    RealEventType.OWN_GOAL.value: "own_goals",
    RealEventType.SAVED_PENALTY_BY_GK.value: "saved_penalties",
    RealEventType.MISSED_PENALTY.value: "missed_penalties",
    RealEventType.ASSIST.value: "assists",
    RealEventType.YELLOW.value: "yellows",
    RealEventType.SECOND_YELLOW_RED.value: "second_yellow_reds",
    RealEventType.RED.value: "reds",
}


class RoundService:
    def __init__(
        self,
        rules: GameRules,
        gameweeks: GameweekRepo,
        fixtures: FixtureRepo,
        events: MatchEventRepo,
        athletics: AthleticsRepo,
        managers: ManagerRepo,
    ) -> None:
        self.rules = rules
        self.gameweeks = gameweeks
        self.fixtures = fixtures
        self.events = events
        self.athletics = athletics
        self.managers = managers
        self._scorer = ValidGoalCalculator(rules)
        self._bonuses = BonusEngine(rules)

    # ------------------------------------------------------------------
    # Live-match event management
    # ------------------------------------------------------------------

    def add_event(
        self,
        gameweek_id: int,
        player_id: int,
        event_type: RealEventType,
        *,
        minute: int | None = None,
        is_extra_time: bool = False,
        is_shootout: bool = False,
    ) -> int:
        """Record one event for a player. Returns the new event_id."""
        self._require_live(gameweek_id)
        return self.events.add(
            gameweek_id, player_id, event_type,
            minute=minute, is_extra_time=is_extra_time, is_shootout=is_shootout,
        )

    def remove_event(self, gameweek_id: int, event_id: int) -> None:
        """Retract a mistaken event. Only allowed while gameweek is LIVE."""
        self._require_live(gameweek_id)
        self.events.remove(event_id)

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize_gameweek(self, gameweek_id: int) -> None:
        """Lock the gameweek and fan out results, bonuses, and stats."""
        self._require_live(gameweek_id)

        # DAL conversion: player_id → manager_id for every starter this week.
        player_manager = self.fixtures.player_manager_map(gameweek_id)
        starter_ids = set(player_manager.keys())

        all_events = self.events.for_players_in_gameweek(gameweek_id, starter_ids)

        for fixture in self.gameweeks.fixtures_for(gameweek_id):
            home_lineup = self.fixtures.lineup_for(fixture.id, fixture.home_manager_id)
            away_lineup = self.fixtures.lineup_for(fixture.id, fixture.away_manager_id)

            home_starters = _starter_ids(home_lineup)
            away_starters = _starter_ids(away_lineup)
            fixture_events = [
                ev for ev in all_events
                if ev.player_id in home_starters or ev.player_id in away_starters
            ]

            score = self._scorer.score(fixture.id, home_starters, away_starters, fixture_events)

            ctx = BonusContext(
                fixture_id=fixture.id,
                home_manager_id=fixture.home_manager_id,
                away_manager_id=fixture.away_manager_id,
                home_goals=score.home_goals,
                away_goals=score.away_goals,
                home_starter_ids=list(home_starters),
                away_starter_ids=list(away_starters),
                events=fixture_events,
            )
            awards = self._bonuses.run(ctx)
            for award in awards:
                self.managers.adjust_balance(award.manager_id, award.amount, reason=award.bonus_type)

        # Flush stats from starter events into all three athletics tables.
        player_deltas: dict[int, dict[str, int]] = {}
        manager_deltas: dict[int, dict[str, int]] = {}
        manager_player_deltas: dict[tuple[int, int], dict[str, int]] = {}

        for ev in all_events:
            if ev.player_id not in starter_ids:
                continue
            field = _EVENT_TO_FIELD.get(
                ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
            )
            if field is None:
                continue

            player_deltas.setdefault(ev.player_id, {})
            player_deltas[ev.player_id][field] = player_deltas[ev.player_id].get(field, 0) + 1

            manager_id = player_manager[ev.player_id]
            manager_deltas.setdefault(manager_id, {})
            manager_deltas[manager_id][field] = manager_deltas[manager_id].get(field, 0) + 1

            key = (manager_id, ev.player_id)
            manager_player_deltas.setdefault(key, {})
            manager_player_deltas[key][field] = manager_player_deltas[key].get(field, 0) + 1

        for player_id, delta in player_deltas.items():
            self.athletics.increment_player(player_id, delta)
        for manager_id, delta in manager_deltas.items():
            self.athletics.increment_manager(manager_id, delta)
        for (manager_id, player_id), delta in manager_player_deltas.items():
            self.athletics.increment_manager_player(manager_id, player_id, delta)

        self.gameweeks.set_status(gameweek_id, GameweekStatus.FINALIZED)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_live(self, gameweek_id: int) -> None:
        gw = self.gameweeks.get(gameweek_id)
        if gw.status is not GameweekStatus.LIVE:
            raise MatchError(
                f"gameweek {gameweek_id} is {gw.status.value}, expected LIVE"
            )


def _starter_ids(lineup) -> set[int]:
    if lineup is None:
        return set()
    starters = lineup.starters or []
    return {s["player_id"] if isinstance(s, dict) else s.player_id for s in starters}
