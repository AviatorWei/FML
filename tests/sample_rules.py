"""Minimal valid `GameRules` instances for unit tests.

Built directly via `GameRules.from_dict` so tests don't need PyYAML.
The `default_rules()` factory returns a Euro-2024-shaped config; tests
that need to tweak a single field can pass `overrides=`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fmlwc.core import GameRules


_BASE: dict[str, Any] = {
    "scope": {"name": "Test League", "short": "TL", "timezone": "UTC"},
    "managers": {"count": 16, "initial_budget": 600, "groups": 4},
    "roster": {
        "total_cap": 20,
        "position_caps": {"G": 2, "D": 6, "M": 8, "F": 4},
    },
    "auction": {
        "rounds": [
            {"index": 1, "opens_at": "2026-06-01T00:00:00+00:00",
             "closes_at": "2026-06-02T00:00:00+00:00"},
        ],
        "min_bid": 10,
        "tiebreaker": "amount_rank_time_draw",
        "cascade": {
            "position_priority": ["F", "M", "D", "G"],
            "invalidate_tie_priority": ["F", "M", "D", "G"],
            "invalidate_tie_within_pos": "lower_rank_first",
        },
        "collusion_block_next_window": True,
    },
    "transfer": {
        "windows": [
            {"opens_at": "2026-06-03T00:00:00+00:00",
             "closes_at": "2026-06-07T00:00:00+00:00",
             "free_sign_period_seconds": 86400},
        ],
        "free_sign_fee": 10,
        "revoke_window_seconds": 900,
        "trades": {"allow_cash": True, "require_counterparty_accept": True},
        "same_window_block_after_free_sign": True,
    },
    "release": {
        "refund": 0,
        "releaser_lifetime_block": True,
        "revoke_window_seconds": 900,
    },
    "lineup": {
        "starters_min": 8,
        "starters_max": 10,
        "appearance_caps": {"G": 1, "D": 3, "M": 4, "F": 2},
        "must_have_positions": ["G"],
        "backward_substitution": {"D": ["M", "F"], "M": ["F"]},
        "default_strategy": "previous_round_then_top_value",
        "misplaced_player_action": "drop_silent",
    },
    "match": {
        "group_stage": {
            "rounds": 3,
            "points": {"W": 3, "D": 1, "L": 0},
            "tiebreak_order": [
                "points", "goals_for", "goals_against_more_first",
                "head_to_head", "real_knockout_qualifiers", "committee_draw",
            ],
        },
        "knockout": {
            "bracket": "euro2024_8team",
            "advance_priority": ["valid_goal", "pk"],
            "pk_score": {
                "goal": 2.0, "assist": 1.0,
                "yellow": -0.3, "second_yellow_red": -0.7, "red": -1.0,
                "real_advance_bonus": 0.5,
            },
            "pk_default_order": ["F", "M", "D", "G"],
            "enable_pick": True,
            "pick_deadline_seconds": 86400,
        },
    },
    "valid_goal": {
        "count_event_types": ["GOAL", "OWN_GOAL", "SAVED_PENALTY_BY_GK"],
        "exclude_penalty_shootout": True,
        "scope_minutes": "regular_and_extra_time",
    },
    "bonuses": {
        "assist": {"enabled": True, "per_event": 5},
        "red_card": {"enabled": True, "per_event": 5},
        "blue_team": {
            "enabled": True,
            "threshold_conceded_gt": 5,
            "threshold_net_lt": -2,
            "formula": "2*conceded - scored",
        },
        "missed_penalty": {"enabled": True, "per_event": 3},
    },
    "prizes": {
        "qualify": {"extra": 80, "weight_formula": "points + 0.5 * goals_for"},
        "advance": {"extra": 80, "weight_formula": "net_goals + 1"},
        "rounding": "half_up_million",
    },
    "injury": {
        "enabled": True,
        "refund_last_signing_fee": True,
        "grant_extra_free_sign_after_window": True,
        "gk_zero_balance_grant": 10,
    },
    "storage": {"driver": "sqlite", "url": "sqlite:///:memory:", "echo": False},
}


def raw_dict(**overrides: Any) -> dict[str, Any]:
    """Return a deep-copied base dict, with top-level overrides applied."""
    cfg = deepcopy(_BASE)
    cfg.update(overrides)
    return cfg


def default_rules(**overrides: Any) -> GameRules:
    return GameRules.from_dict(raw_dict(**overrides))
