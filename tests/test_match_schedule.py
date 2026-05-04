"""Tests for fmlwc.domain.match.schedule."""

from __future__ import annotations

import pytest

from fmlwc.domain.match.schedule import (
    BracketBuilder,
    CircleMethodPairing,
    Scheduler,
)
from tests.sample_rules import default_rules


def test_circle_method_4_teams_3_rounds_each_pair_once():
    p = CircleMethodPairing()
    rounds = p.round_robin([1, 2, 3, 4])
    assert len(rounds) == 3
    # 6 unique unordered pairs across all rounds
    pairs = set()
    for r in rounds:
        assert len(r) == 2
        for f in r:
            pair = frozenset((f.home_manager_id, f.away_manager_id))
            pairs.add(pair)
    assert len(pairs) == 6


def test_circle_method_no_self_pairing():
    p = CircleMethodPairing()
    rounds = p.round_robin([1, 2, 3, 4])
    for r in rounds:
        for f in r:
            assert f.home_manager_id != f.away_manager_id


def test_circle_method_handles_odd_with_bye():
    p = CircleMethodPairing()
    rounds = p.round_robin([1, 2, 3])
    # 3 teams = 3 rounds where each round has 1 game (the third sits out)
    assert len(rounds) == 3
    for r in rounds:
        assert len(r) == 1


def test_bracket_quarterfinals_euro2024():
    b = BracketBuilder(default_rules())
    standings = {
        "A": [101, 102],
        "B": [103, 104],
        "C": [105, 106],
        "D": [107, 108],
    }
    qfs = b.quarterfinals(standings)
    assert len(qfs) == 4
    # QF1: A1 vs B2 = 101 vs 104
    assert (qfs[0].home_manager_id, qfs[0].away_manager_id) == (101, 104)
    assert qfs[0].bracket_slot == "QF1"
    # QF2: C1 vs D2 = 105 vs 108
    assert (qfs[1].home_manager_id, qfs[1].away_manager_id) == (105, 108)
    # QF3: B1 vs A2 = 103 vs 102
    assert (qfs[2].home_manager_id, qfs[2].away_manager_id) == (103, 102)
    # QF4: D1 vs C2 = 107 vs 106
    assert (qfs[3].home_manager_id, qfs[3].away_manager_id) == (107, 106)


def test_bracket_unknown_raises():
    from tests.sample_rules import raw_dict
    cfg = raw_dict()
    cfg["match"]["knockout"]["bracket"] = "wat"
    from fmlwc.core import GameRules
    b = BracketBuilder(GameRules.from_dict(cfg))
    with pytest.raises(ValueError, match="unknown bracket"):
        b.quarterfinals({"A": [1, 2], "B": [3, 4], "C": [5, 6], "D": [7, 8]})


def test_bracket_next_round_pairs_winners():
    b = BracketBuilder(default_rules())
    sf = b.next_round([1, 2, 3, 4])
    assert len(sf) == 2
    assert (sf[0].home_manager_id, sf[0].away_manager_id) == (1, 2)
    assert (sf[1].home_manager_id, sf[1].away_manager_id) == (3, 4)


def test_scheduler_draw_groups_deterministic_with_seed():
    s1 = Scheduler(default_rules(), seed=42)
    g1 = s1.draw_groups(list(range(1, 17)))
    s2 = Scheduler(default_rules(), seed=42)
    g2 = s2.draw_groups(list(range(1, 17)))
    assert g1 == g2
    assert set(g1.keys()) == {"A", "B", "C", "D"}
    assert sum(len(v) for v in g1.values()) == 16
    # All managers placed exactly once
    flat = [m for v in g1.values() for m in v]
    assert sorted(flat) == list(range(1, 17))


def test_scheduler_uneven_split_raises():
    s = Scheduler(default_rules())
    with pytest.raises(ValueError, match="equal groups"):
        s.draw_groups(list(range(1, 18)))   # 17 managers, 4 groups
