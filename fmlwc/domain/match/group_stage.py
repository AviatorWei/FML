"""Group-stage standings (rule 五.4).

Tiebreakers, in order:
    1. points
    2. goals_for           (more first)
    3. goals_against_more_first   (note: rule 五.4 says 失球数多者排名靠前)
    4. head_to_head        (mini-table: only games among tied teams)
    5. real_knockout_qualifiers (count of own roster players who advanced)
    6. committee_draw      (deterministic seed)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ...core.config import GameRules


@dataclass
class StandingRow:
    manager_id: int
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def net_goals(self) -> int:
        return self.goals_for - self.goals_against


@dataclass
class _MatchRecord:
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int


@dataclass
class GroupStandings:
    rules: GameRules
    rows: dict[int, StandingRow] = field(default_factory=dict)
    history: list[_MatchRecord] = field(default_factory=list)

    def ensure(self, manager_id: int) -> None:
        if manager_id not in self.rows:
            self.rows[manager_id] = StandingRow(manager_id)

    def apply_result(self, home_id, away_id, home_goals, away_goals) -> None:
        self.ensure(home_id)
        self.ensure(away_id)
        h, a = self.rows[home_id], self.rows[away_id]
        h.played += 1; a.played += 1
        h.goals_for += home_goals; h.goals_against += away_goals
        a.goals_for += away_goals; a.goals_against += home_goals
        pts = self.rules.match.group_stage.points
        if home_goals > away_goals:
            h.won += 1; a.lost += 1
            h.points += pts.get("W", 3); a.points += pts.get("L", 0)
        elif home_goals < away_goals:
            a.won += 1; h.lost += 1
            a.points += pts.get("W", 3); h.points += pts.get("L", 0)
        else:
            h.drawn += 1; a.drawn += 1
            h.points += pts.get("D", 1); a.points += pts.get("D", 1)
        self.history.append(_MatchRecord(home_id, away_id, home_goals, away_goals))

    def ranked(
        self,
        real_qual_lookup: Callable[[int], int] | None = None,
    ) -> list[StandingRow]:
        """Return rows sorted by configured tiebreak chain."""
        order = list(self.rules.match.group_stage.tiebreak_order)
        rows = list(self.rows.values())

        def _h2h_points(group: list[int]) -> dict[int, int]:
            mini = {mid: 0 for mid in group}
            pts = self.rules.match.group_stage.points
            gset = set(group)
            for m in self.history:
                if m.home_id in gset and m.away_id in gset:
                    if m.home_goals > m.away_goals:
                        mini[m.home_id] += pts.get("W", 3); mini[m.away_id] += pts.get("L", 0)
                    elif m.home_goals < m.away_goals:
                        mini[m.away_id] += pts.get("W", 3); mini[m.home_id] += pts.get("L", 0)
                    else:
                        mini[m.home_id] += pts.get("D", 1); mini[m.away_id] += pts.get("D", 1)
            return mini

        def _draw_seed(mid: int) -> int:
            h = hashlib.sha256(f"committee:{mid}".encode()).digest()
            return int.from_bytes(h[:4], "big")

        def key_for(rule: str, row: StandingRow, h2h: dict[int, int] | None):
            if rule == "points": return -row.points
            if rule == "goals_for": return -row.goals_for
            if rule == "goals_against_more_first":
                return -row.goals_against
            if rule == "goals_against": return row.goals_against
            if rule == "net_goals": return -row.net_goals
            if rule == "head_to_head":
                return -(h2h or {}).get(row.manager_id, 0)
            if rule == "real_knockout_qualifiers":
                return -(real_qual_lookup(row.manager_id) if real_qual_lookup else 0)
            if rule == "committee_draw":
                return _draw_seed(row.manager_id)
            raise ValueError(f"unknown tiebreak rule: {rule}")

        # Multi-key sort with head_to_head re-evaluated within tied groups.
        # Strategy: progressive partition. Start with all rows in one group,
        # split by each key in order; within tied groups, re-evaluate next key
        # (with head_to_head computed against that tied subgroup only).
        groups = [rows]
        for rule in order:
            new_groups = []
            for g in groups:
                if len(g) <= 1:
                    new_groups.append(g)
                    continue
                if rule == "head_to_head":
                    h2h = _h2h_points([r.manager_id for r in g])
                    g_sorted = sorted(g, key=lambda r: key_for(rule, r, h2h))
                else:
                    g_sorted = sorted(g, key=lambda r: key_for(rule, r, None))
                # re-partition by equal key
                bucket = []
                last_k = object()
                for r in g_sorted:
                    k = key_for(rule, r, _h2h_points([rr.manager_id for rr in g])
                                if rule == "head_to_head" else None)
                    if k != last_k and bucket:
                        new_groups.append(bucket)
                        bucket = []
                    bucket.append(r)
                    last_k = k
                if bucket:
                    new_groups.append(bucket)
            groups = new_groups

        return [r for g in groups for r in g]
