"""Per-player winner selection (rule 二.6).

Sort key (lower wins):
    1. -amount              (higher amount first)
    2. rank_in_position
    3. submission.received_at
    4. committee_draw_seed  (deterministic prng over (round_id, player_id, manager_id))

Pluggable: subclass `TiebreakerStrategy` for non-default rules.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class CandidateBid:
    """View of a VALID bid scoped to a single player, ready for ranking."""

    bid_id: int
    manager_id: int
    amount: int
    rank_in_position: int
    submission_received_at: datetime
    draw_seed: int


class TiebreakerStrategy(ABC):
    @abstractmethod
    def select_winner(self, candidates: Sequence[CandidateBid]) -> CandidateBid: ...


class AmountRankTimeDraw(TiebreakerStrategy):
    """Default strategy matching FME-2021 rule 二.6."""

    def select_winner(self, candidates: Sequence[CandidateBid]) -> CandidateBid:
        if not candidates:
            raise ValueError("no candidates to select winner from")

        return min(
            candidates,
            key=lambda b: (
                -b.amount,
                b.rank_in_position,
                b.submission_received_at,
                b.draw_seed,
            ),
        )


def get_strategy(name: str) -> TiebreakerStrategy:
    """Factory called by AuctionService based on YAML key."""
    if name == "amount_rank_time_draw":
        return AmountRankTimeDraw()
    raise ValueError(f"unknown tiebreaker strategy: {name}")


def deterministic_draw_seed(round_id: int, player_id: int, manager_id: int) -> int:
    """Stable hash for the committee_draw last-resort tiebreak."""
    h = hashlib.sha256(f"{round_id}:{player_id}:{manager_id}".encode()).digest()
    return int.from_bytes(h[:4], "big")
