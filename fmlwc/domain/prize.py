"""Qualifier and advancement prizes (rule 七.3 + 七.4).

Qualify prize:
    pool = sum(balance(group_stage_eliminated))
    weight(m) = points(m) + 0.5 * goals_for(m)
    share(m) = round_half_up(pool * weight(m) / sum(weights)) + 80m

Advance prize:
    pool = sum(balance(eliminated_in_round))
    weight(m) = net_goals_in_round(m) + 1
    share(m) = round_half_up(pool * weight(m) / sum(weights)) + 80m
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from ..core.config import GameRules


@dataclass(frozen=True)
class PrizePayout:
    manager_id: int
    bucket: str
    amount: int  # unit: million EUR


def round_half_up(value: float) -> int:
    """Round to the nearest integer (millions), half-up.

    Amounts in this engine are expressed in millions of euros, so this
    is rule 七.5's "四舍五入" (rounding to the nearest 1m).
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PrizeDistributor:
    def __init__(self, rules: GameRules, managers=None) -> None:
        self.rules = rules
        self.managers = managers

    def distribute_qualify(
        self,
        eliminated_balances: Mapping[int, int],
        qualifier_stats: Mapping[int, dict],
    ) -> list[PrizePayout]:
        pool = sum(eliminated_balances.values())
        weights = {
            mid: stats.get("points", 0) + 0.5 * stats.get("goals_for", 0)
            for mid, stats in qualifier_stats.items()
        }
        total_w = sum(weights.values())
        extra = self.rules.prizes.qualify.extra
        out = []
        for mid, w in weights.items():
            base = (pool * w / total_w) if total_w > 0 else 0
            share = round_half_up(base) + extra
            out.append(PrizePayout(mid, "QUALIFY", share))
        return out

    def distribute_advance(
        self,
        round_label: str,
        eliminated_balances: Mapping[int, int],
        advancer_stats: Mapping[int, dict],
    ) -> list[PrizePayout]:
        pool = sum(eliminated_balances.values())
        weights = {
            mid: stats.get("net_goals", 0) + 1
            for mid, stats in advancer_stats.items()
        }
        total_w = sum(weights.values())
        extra = self.rules.prizes.advance.extra
        out = []
        for mid, w in weights.items():
            base = (pool * w / total_w) if total_w > 0 else 0
            share = round_half_up(base) + extra
            out.append(PrizePayout(mid, f"ADVANCE_{round_label}", share))
        return out
