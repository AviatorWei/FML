"""Frozen dataclass tree for GameRules. Imported by config.py.

Kept separate to keep the public config.py file small.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import Position


@dataclass(frozen=True)
class ScopeConfig:
    name: str
    short: str
    timezone: str


@dataclass(frozen=True)
class ManagersConfig:
    count: int
    initial_budget: int  # unit: million EUR
    groups: int


@dataclass(frozen=True)
class RosterConfig:
    total_cap: int
    position_caps: dict[Position, int]


@dataclass(frozen=True)
class AuctionRoundSpec:
    index: int
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True)
class AuctionCascadeConfig:
    position_priority: list[Position]
    invalidate_tie_priority: list[Position]
    invalidate_tie_within_pos: str


@dataclass(frozen=True)
class AuctionConfig:
    rounds: list[AuctionRoundSpec]
    min_bid: int  # unit: million EUR
    tiebreaker: str
    cascade: AuctionCascadeConfig
    collusion_block_next_window: bool


@dataclass(frozen=True)
class TransferWindowSpec:
    opens_at: datetime
    closes_at: datetime
    free_sign_period_seconds: int


@dataclass(frozen=True)
class TransferConfig:
    windows: list[TransferWindowSpec]
    free_sign_fee: int  # unit: million EUR
    revoke_window_seconds: int
    trades_allow_cash: bool
    trades_require_counterparty_accept: bool
    same_window_block_after_free_sign: bool


@dataclass(frozen=True)
class ReleaseConfig:
    refund: int  # unit: million EUR
    releaser_lifetime_block: bool
    revoke_window_seconds: int


@dataclass(frozen=True)
class LineupConfig:
    starters_min: int
    starters_max: int
    appearance_caps: dict[Position, int]
    must_have_positions: list[Position]
    backward_substitution: dict[Position, list[Position]]
    default_strategy: str
    misplaced_player_action: str


@dataclass(frozen=True)
class GroupStageConfig:
    rounds: int
    points: dict[str, int]
    tiebreak_order: list[str]


@dataclass(frozen=True)
class PkScoreConfig:
    goal: float
    assist: float
    yellow: float
    second_yellow_red: float
    red: float
    real_advance_bonus: float


@dataclass(frozen=True)
class KnockoutConfig:
    bracket: str
    advance_priority: list[str]
    pk_score: PkScoreConfig
    pk_default_order: list[Position]
    enable_pick: bool
    pick_deadline_seconds: int


@dataclass(frozen=True)
class MatchConfig:
    group_stage: GroupStageConfig
    knockout: KnockoutConfig


@dataclass(frozen=True)
class ValidGoalConfig:
    count_event_types: list[str]
    exclude_penalty_shootout: bool
    scope_minutes: str


@dataclass(frozen=True)
class BlueTeamConfig:
    enabled: bool
    threshold_conceded_gt: int
    threshold_net_lt: int
    formula: str


@dataclass(frozen=True)
class FlatBonusConfig:
    enabled: bool
    per_event: int  # unit: million EUR


@dataclass(frozen=True)
class BonusesConfig:
    assist: FlatBonusConfig
    red_card: FlatBonusConfig
    blue_team: BlueTeamConfig
    missed_penalty: FlatBonusConfig


@dataclass(frozen=True)
class PrizeBucketConfig:
    extra: int  # unit: million EUR
    weight_formula: str


@dataclass(frozen=True)
class PrizesConfig:
    qualify: PrizeBucketConfig
    advance: PrizeBucketConfig
    rounding: str


@dataclass(frozen=True)
class InjuryConfig:
    enabled: bool
    refund_last_signing_fee: bool
    grant_extra_free_sign_after_window: bool
    gk_zero_balance_grant: int  # unit: million EUR


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    url: str
    echo: bool
