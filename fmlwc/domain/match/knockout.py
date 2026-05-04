"""Knockout-stage PK system (rule 六.3 + 六.4).

PK score per starter:
    +2 per FME goal
    +1 per assist
    -0.3 per yellow
    -0.7 per second-yellow-red
    -1.0 per red
    +0.5 if their real club advanced to next Euro round

Resolution:
    Compare top-5 PK score sum. If equal, compare position 6 alone, then 7,
    etc. If one side runs out of starters, the other wins. Both exhaust = draw.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.config import GameRules
from ...core.enums import Position, RealEventType


@dataclass(frozen=True)
class PkOutcome:
    home_total_top5: float
    away_total_top5: float
    winner_manager_id: int | None
    decided_at_position: int   # 5 = decided on top-5 sum; >5 = which extra slot decided


class PkResolver:
    def __init__(self, rules: GameRules) -> None:
        self.rules = rules
        self.cfg = rules.match.knockout.pk_score

    def player_pk_score(
        self,
        player_id: int,
        events_for_player,
        real_team_advanced: bool,
    ) -> float:
        cfg = self.cfg
        score = 0.0
        for ev in events_for_player:
            if getattr(ev, "is_shootout", False):
                continue
            et = ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
            if et in (RealEventType.GOAL.value, RealEventType.OWN_GOAL.value,
                      RealEventType.SAVED_PENALTY_BY_GK.value):
                score += cfg.goal
            elif et == RealEventType.ASSIST.value:
                score += cfg.assist
            elif et == RealEventType.YELLOW.value:
                score += cfg.yellow
            elif et == RealEventType.SECOND_YELLOW_RED.value:
                score += cfg.second_yellow_red
            elif et == RealEventType.RED.value:
                score += cfg.red
        if real_team_advanced:
            score += cfg.real_advance_bonus
        return score

    def resolve(
        self,
        home_pk_order,
        away_pk_order,
        events_by_player,
        advancement_by_player,
        home_manager_id,
        away_manager_id,
    ) -> PkOutcome:
        def s(pid):
            return self.player_pk_score(
                pid,
                events_by_player.get(pid, []),
                advancement_by_player.get(pid, False),
            )

        home_scores = [s(p) for p in home_pk_order]
        away_scores = [s(p) for p in away_pk_order]

        h_top5 = sum(home_scores[:5])
        a_top5 = sum(away_scores[:5])
        if h_top5 != a_top5:
            winner = home_manager_id if h_top5 > a_top5 else away_manager_id
            return PkOutcome(h_top5, a_top5, winner, 5)

        # Compare position 6, 7, ...
        i = 5
        max_len = max(len(home_scores), len(away_scores))
        while i < max_len:
            h = home_scores[i] if i < len(home_scores) else None
            a = away_scores[i] if i < len(away_scores) else None
            if h is None and a is None:
                break
            if h is None:
                return PkOutcome(h_top5, a_top5, away_manager_id, i + 1)
            if a is None:
                return PkOutcome(h_top5, a_top5, home_manager_id, i + 1)
            if h != a:
                winner = home_manager_id if h > a else away_manager_id
                return PkOutcome(h_top5, a_top5, winner, i + 1)
            i += 1
        return PkOutcome(h_top5, a_top5, None, i)

    def default_pk_order(self, starters):
        """Rule 六.3 default: F, M, D, G; within position keep starter order."""
        order = self.rules.match.knockout.pk_default_order
        bucket = {p: [] for p in order}
        for pid, pos in starters:
            bucket.setdefault(pos, []).append(pid)
        out = []
        for p in order:
            out.extend(bucket.get(p, []))
        return out
