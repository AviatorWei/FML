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
    conditional_release_enabled: bool  # 条件解约: 负数 rank 标记可解约的已有球员


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
    # FML 第五十条: a player may belong to at most N managers per season
    # (0 = unlimited, FML 2024-25 uses 3), and be traded at most once per
    # window. 第四十九条(2): players-for-cash requires ≥ min_cash_per_player
    # per player moved.
    max_owners_per_season: int = 0
    max_trades_per_window_per_player: int = 0
    min_cash_per_player: int = 0


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
    # Composite caps across several positions (FML 第三十六条):
    # e.g. ((F,), 2), ((F, W), 4), ((F, W, M), 7). Empty for FME-2021.
    group_caps: tuple[tuple[tuple[Position, ...], int], ...] = ()


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
    # FML 第十二条: 5m per opponent FML goal each round (paid next window).
    conceded_goal: FlatBonusConfig = FlatBonusConfig(enabled=False, per_event=0)
    # FMC 第六十七条(4): 主场失球奖 — home side, 5m per goal conceded.
    home_conceded: FlatBonusConfig = FlatBonusConfig(enabled=False, per_event=0)


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


@dataclass(frozen=True)
class CupConfig:
    """Dual-competition (league + cup) mode.

    * ``extra_teams``          — real-team codes that exist ONLY in the cup;
                                 their players are cup-exclusive signings.
    * ``league_teams_in_cup``  — real-team codes from the league pool whose
                                 players are dual-eligible (league AND cup)
                                 while the cup is in its group stage.
    * ``separate_after_group`` — when True, once the cup enters knockout,
                                 eligibility separates: every dual-eligible
                                 player counts for exactly one competition
                                 (their declared one; undeclared → LEAGUE).
    """

    enabled: bool
    extra_teams: tuple[str, ...]
    league_teams_in_cup: tuple[str, ...]
    separate_after_group: bool
    # FMC 第十三条: initial cup wallet (only spendable on cup-exclusive
    # players during the cup group stage; unrestricted after separation).
    initial_cup_budget: int = 0


DEFAULT_CUP = CupConfig(
    enabled=False,
    extra_teams=(),
    league_teams_in_cup=(),
    separate_after_group=True,
    initial_cup_budget=0,
)
