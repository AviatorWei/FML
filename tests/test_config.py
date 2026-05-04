"""Tests for fmlwc.core.config — YAML/dict → GameRules."""

from __future__ import annotations

import pytest

from fmlwc.core import GameRules
from fmlwc.core.config import _as_int, _parse_dt, _parse_position_map
from fmlwc.core.enums import Position
from fmlwc.core.exceptions import ConfigError

from tests.sample_rules import default_rules, raw_dict


def test_default_rules_loads_all_sections():
    r = default_rules()
    assert r.scope.name == "Test League"
    assert r.managers.count == 16
    assert r.managers.initial_budget == 600
    assert r.roster.position_caps[Position.G] == 2
    assert r.roster.position_caps[Position.F] == 4
    assert r.auction.min_bid == 10
    assert r.auction.cascade.position_priority == [Position.F, Position.M, Position.D, Position.G]
    assert r.lineup.starters_min == 8
    assert r.lineup.backward_substitution[Position.D] == [Position.M, Position.F]
    assert r.match.knockout.pk_score.goal == 2.0


def test_missing_top_level_section_raises():
    cfg = raw_dict()
    del cfg["bonuses"]
    with pytest.raises(ConfigError, match="bonuses"):
        GameRules.from_dict(cfg)


def test_unknown_position_in_caps():
    cfg = raw_dict()
    cfg["roster"]["position_caps"]["X"] = 1
    with pytest.raises(ConfigError, match="position"):
        GameRules.from_dict(cfg)


def test_m_shorthand_int_coercion():
    assert _as_int("600m", "x") == 600
    assert _as_int("10m", "x") == 10
    assert _as_int(42, "x") == 42
    with pytest.raises(ConfigError):
        _as_int("not-a-number", "x")
    with pytest.raises(ConfigError):
        _as_int(True, "x")        # booleans rejected


def test_parse_position_map_rejects_non_mapping():
    with pytest.raises(ConfigError):
        _parse_position_map(["G", "D"], "x")  # type: ignore[arg-type]


def test_parse_dt_handles_z_suffix_and_naive():
    z = _parse_dt("2026-06-01T00:00:00Z", "x")
    assert z.tzinfo is not None
    naive = _parse_dt("2026-06-01T00:00:00", "x")
    assert naive.tzinfo is not None  # promoted to UTC


def test_blue_team_formula_string_preserved():
    r = default_rules()
    assert r.bonuses.blue_team.formula == "2*conceded - scored"


def test_top_level_must_be_mapping():
    with pytest.raises(ConfigError):
        GameRules.from_dict([1, 2, 3])  # type: ignore[arg-type]
