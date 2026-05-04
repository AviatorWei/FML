"""Tests for fmlwc.domain.lineup.validator."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fmlwc.core.enums import AcquisitionVia, Position
from fmlwc.core.exceptions import LineupError
from fmlwc.domain.lineup.validator import LineupValidator, StarterInput

from tests.fakes import FakePlayer, make_repos


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _setup(rules):
    """Build a 14-player roster covering each position."""
    players = []
    counts = {Position.G: 2, Position.D: 5, Position.M: 5, Position.F: 2}
    pid = 0
    by_pos = {p: [] for p in Position}
    for pos, n in counts.items():
        for _ in range(n):
            pid += 1
            p = FakePlayer(id=pid, name=f"P{pid}", position=pos)
            players.append(p)
            by_pos[pos].append(pid)
    mgr, plr, _ = make_repos(players=players)
    from tests.fakes import FakeManager
    mgr.managers[1] = FakeManager(id=1, display_name="M1", balance=600)
    for p in players:
        mgr.add_to_roster(1, p.id, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=10)
    return LineupValidator(rules, plr, mgr), by_pos


def _ok_lineup(by_pos):
    """1 G + 3 D + 4 M + 2 F = 10 starters."""
    return [
        StarterInput(by_pos[Position.G][0], Position.G),
        StarterInput(by_pos[Position.D][0], Position.D),
        StarterInput(by_pos[Position.D][1], Position.D),
        StarterInput(by_pos[Position.D][2], Position.D),
        StarterInput(by_pos[Position.M][0], Position.M),
        StarterInput(by_pos[Position.M][1], Position.M),
        StarterInput(by_pos[Position.M][2], Position.M),
        StarterInput(by_pos[Position.M][3], Position.M),
        StarterInput(by_pos[Position.F][0], Position.F),
        StarterInput(by_pos[Position.F][1], Position.F),
    ]


def test_canonical_lineup_passes():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    out = v.validate(1, _ok_lineup(by_pos))
    assert len(out.accepted) == 10
    assert out.dropped == []


def test_too_few_starters_raises():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)[:7]      # 7 starters
    with pytest.raises(LineupError, match="too few"):
        v.validate(1, line)


def test_too_many_starters_raises():
    """With caps 1G/3D/4M/2F summing to 10, any 11th starter must already
    trip a position cap; we just need a LineupError of some kind."""
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    line.append(StarterInput(by_pos[Position.D][3], Position.F))
    with pytest.raises(LineupError):
        v.validate(1, line)


def test_too_many_starters_with_loosened_caps():
    """Loosen caps so the 'too many' branch is actually reachable."""
    from tests.sample_rules import raw_dict
    cfg = raw_dict()
    cfg["lineup"]["appearance_caps"] = {"G": 1, "D": 5, "M": 5, "F": 5}
    cfg["lineup"]["starters_max"] = 10
    from fmlwc.core import GameRules
    rules = GameRules.from_dict(cfg)
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    line.append(StarterInput(by_pos[Position.D][3], Position.D))
    with pytest.raises(LineupError, match="too many"):
        v.validate(1, line)


def test_no_goalkeeper_raises():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    # replace the GK with a backward-D-as-? — not legal anyway, so use 8 outfielders
    line = [
        StarterInput(by_pos[Position.D][0], Position.D),
        StarterInput(by_pos[Position.D][1], Position.D),
        StarterInput(by_pos[Position.D][2], Position.D),
        StarterInput(by_pos[Position.M][0], Position.M),
        StarterInput(by_pos[Position.M][1], Position.M),
        StarterInput(by_pos[Position.M][2], Position.M),
        StarterInput(by_pos[Position.F][0], Position.F),
        StarterInput(by_pos[Position.F][1], Position.F),
    ]
    with pytest.raises(LineupError, match="must include at least one G"):
        v.validate(1, line)


def test_appearance_cap_F_exceeded():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    # swap one M for an additional F-slot -> 3 F violates cap
    line[4] = StarterInput(by_pos[Position.D][3], Position.F)  # D backward to F
    line.append(StarterInput(by_pos[Position.D][4], Position.F))   # 11th
    line.pop(5)  # back to 10
    with pytest.raises(LineupError, match="appearance cap"):
        v.validate(1, line)


def test_backward_substitution_D_as_M_accepted():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    # Move a D into the M slot
    line[4] = StarterInput(by_pos[Position.D][3], Position.M)
    out = v.validate(1, line)
    assert len(out.accepted) == 10


def test_misplaced_F_in_M_silently_dropped():
    """F cannot back-fill M (rule 四.4). Player gets silently dropped."""
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    # Try to put F in M slot, swap one of the original Ms back so we still
    # have a legal-size lineup. Total counted: misplaced F dropped, lineup
    # ends up at 9 (still >=8).
    line = _ok_lineup(by_pos)
    line[4] = StarterInput(by_pos[Position.F][0], Position.M)  # F as M = misplaced
    # avoid double-listing F[0]: replace last F slot with another player
    line[-2] = StarterInput(by_pos[Position.D][3], Position.F)  # D as F (legal)
    out = v.validate(1, line)
    dropped_ids = [d.player_id for d in out.dropped]
    assert by_pos[Position.F][0] in dropped_ids
    assert len(out.accepted) == 9


def test_player_not_on_roster_dropped():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    # add a bogus player_id 999 to the lineup
    line[5] = StarterInput(999, Position.M)
    out = v.validate(1, line)
    assert any(d.player_id == 999 and "roster" in d.reason for d in out.dropped)
    assert len(out.accepted) == 9


def test_duplicate_in_lineup_dropped():
    from tests.sample_rules import default_rules
    rules = default_rules()
    v, by_pos = _setup(rules)
    line = _ok_lineup(by_pos)
    # duplicate the first GK in another slot
    line.append(StarterInput(by_pos[Position.G][0], Position.M))
    out = v.validate(1, line)
    assert any("duplicate" in d.reason for d in out.dropped)
