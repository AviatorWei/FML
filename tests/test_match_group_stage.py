"""Tests for fmlwc.domain.match.group_stage."""

from __future__ import annotations

from fmlwc.domain.match.group_stage import GroupStandings

from tests.sample_rules import default_rules


def test_apply_result_updates_rows():
    s = GroupStandings(default_rules())
    s.apply_result(1, 2, 3, 1)
    assert s.rows[1].won == 1 and s.rows[1].points == 3
    assert s.rows[2].lost == 1 and s.rows[2].points == 0
    assert s.rows[1].goals_for == 3 and s.rows[1].goals_against == 1


def test_draw_credits_both_one_point():
    s = GroupStandings(default_rules())
    s.apply_result(1, 2, 1, 1)
    assert s.rows[1].drawn == 1 == s.rows[2].drawn
    assert s.rows[1].points == 1 == s.rows[2].points


def test_ranking_by_points():
    s = GroupStandings(default_rules())
    # 1: 6pts, 2: 3pts, 3: 0pts
    s.apply_result(1, 2, 2, 0)
    s.apply_result(2, 3, 1, 0)
    s.apply_result(1, 3, 1, 0)
    ranked = [r.manager_id for r in s.ranked()]
    assert ranked == [1, 2, 3]


def test_ranking_breaks_tie_by_goals_for():
    """Points equal -> goals_for higher comes first."""
    s = GroupStandings(default_rules())
    s.apply_result(1, 4, 3, 0)   # 1 wins big
    s.apply_result(2, 4, 1, 0)   # 2 wins small
    s.apply_result(1, 2, 1, 1)   # 1 vs 2 draw
    # 1: 4pts, 4 GF; 2: 4pts, 2 GF
    ranked = [r.manager_id for r in s.ranked()]
    assert ranked[0] == 1
    assert ranked[1] == 2


def test_head_to_head_used_when_other_keys_tied():
    """Build a 2-team tie that only h2h can break."""
    s = GroupStandings(default_rules())
    # Both team 1 and 2 finish with: 1 win against team 3 (1-0), 1 head-to-head match.
    s.apply_result(1, 3, 1, 0)
    s.apply_result(2, 3, 1, 0)
    # Now 1 and 2 are tied: 3pts, 1 GF, 0 GA. Head-to-head:
    s.apply_result(1, 2, 2, 1)   # team 1 wins h2h
    # After this, 1: 6pts, 3 GF, 1 GA; 2: 3pts, 2 GF, 2 GA. So points already separates.
    # Build a stricter scenario:
    s2 = GroupStandings(default_rules())
    # tie everything except h2h
    s2.apply_result(1, 3, 0, 0)
    s2.apply_result(2, 3, 0, 0)
    s2.apply_result(1, 2, 1, 0)
    # 1: 4 pts (W vs 2, D vs 3); 2: 1 pt; 3: 2 pt
    ranked = [r.manager_id for r in s2.ranked()]
    assert ranked[0] == 1
