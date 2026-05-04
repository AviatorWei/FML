"""Single-match bonuses (rule 七.2).

Each rule is one BonusRule subclass. BonusEngine iterates them.

Built-in:
    AssistBonus       - +5m per assist by starters
    RedCardBonus      - +5m per red card on starters
    BlueTeamBonus     - if conceded > X AND net < Y -> formula-based
    MissedPenaltyBonus - +3m per regulation/ET missed penalty by starter
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...core.config import GameRules
from ...core.enums import RealEventType


@dataclass(frozen=True)
class Award:
    manager_id: int
    fixture_id: int
    bonus_type: str
    amount: int  # unit: million EUR


@dataclass
class BonusContext:
    fixture_id: int
    home_manager_id: int
    away_manager_id: int
    home_goals: int
    away_goals: int
    home_starter_ids: list
    away_starter_ids: list
    events: list


class BonusRule(ABC):
    @abstractmethod
    def compute(self, ctx: BonusContext) -> list[Award]: ...


def _count_event_for_starters(ctx, event_type, starters):
    starter_set = set(starters)
    n = 0
    for ev in ctx.events:
        if getattr(ev, "is_shootout", False):
            continue
        et = ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
        if et == event_type and ev.real_player_id in starter_set:
            n += 1
    return n


class AssistBonus(BonusRule):
    def __init__(self, per_event):
        self.per_event = per_event

    def compute(self, ctx):
        out = []
        h = _count_event_for_starters(ctx, RealEventType.ASSIST.value, ctx.home_starter_ids)
        a = _count_event_for_starters(ctx, RealEventType.ASSIST.value, ctx.away_starter_ids)
        if h:
            out.append(Award(ctx.home_manager_id, ctx.fixture_id, "ASSIST", h * self.per_event))
        if a:
            out.append(Award(ctx.away_manager_id, ctx.fixture_id, "ASSIST", a * self.per_event))
        return out


class RedCardBonus(BonusRule):
    def __init__(self, per_event):
        self.per_event = per_event

    def compute(self, ctx):
        out = []
        for side, mid, starters in [
            ("HOME", ctx.home_manager_id, ctx.home_starter_ids),
            ("AWAY", ctx.away_manager_id, ctx.away_starter_ids),
        ]:
            n = 0
            for et in (RealEventType.RED.value, RealEventType.SECOND_YELLOW_RED.value):
                n += _count_event_for_starters(ctx, et, starters)
            if n:
                out.append(Award(mid, ctx.fixture_id, "RED_CARD", n * self.per_event))
        return out


class MissedPenaltyBonus(BonusRule):
    def __init__(self, per_event):
        self.per_event = per_event

    def compute(self, ctx):
        out = []
        h = _count_event_for_starters(ctx, RealEventType.MISSED_PENALTY.value, ctx.home_starter_ids)
        a = _count_event_for_starters(ctx, RealEventType.MISSED_PENALTY.value, ctx.away_starter_ids)
        if h:
            out.append(Award(ctx.home_manager_id, ctx.fixture_id, "MISSED_PENALTY", h * self.per_event))
        if a:
            out.append(Award(ctx.away_manager_id, ctx.fixture_id, "MISSED_PENALTY", a * self.per_event))
        return out


# --- safe formula evaluator for blue_team -----------------------------------

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


def _safe_eval(formula: str, env: dict) -> float:
    """Evaluate `formula` with only arithmetic and `env` names allowed.

    No function calls, attribute access, or subscripts.
    """
    tree = ast.parse(formula, mode="eval")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"forbidden constant: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError(f"unknown name: {node.id}")
            return env[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARYOPS):
            v = visit(node.operand)
            return +v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            l, r = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return l + r
            if isinstance(node.op, ast.Sub): return l - r
            if isinstance(node.op, ast.Mult): return l * r
            if isinstance(node.op, ast.Div): return l / r
            if isinstance(node.op, ast.FloorDiv): return l // r
            if isinstance(node.op, ast.Mod): return l % r
        raise ValueError(f"forbidden expression: {ast.dump(node)}")

    return visit(tree)


class BlueTeamBonus(BonusRule):
    def __init__(self, conceded_gt: int, net_lt: int, formula: str):
        self.conceded_gt = conceded_gt
        self.net_lt = net_lt
        self.formula = formula

    def compute(self, ctx):
        out = []
        for mid, scored, conceded in [
            (ctx.home_manager_id, ctx.home_goals, ctx.away_goals),
            (ctx.away_manager_id, ctx.away_goals, ctx.home_goals),
        ]:
            net = scored - conceded
            if conceded > self.conceded_gt and net < self.net_lt:
                amount = int(_safe_eval(self.formula, {"conceded": conceded, "scored": scored}))
                out.append(Award(mid, ctx.fixture_id, "BLUE_TEAM", amount))
        return out


class BonusEngine:
    def __init__(self, rules: GameRules) -> None:
        cfg = rules.bonuses
        self.rules: list[BonusRule] = []
        if cfg.assist.enabled:
            self.rules.append(AssistBonus(cfg.assist.per_event))
        if cfg.red_card.enabled:
            self.rules.append(RedCardBonus(cfg.red_card.per_event))
        if cfg.blue_team.enabled:
            self.rules.append(
                BlueTeamBonus(
                    cfg.blue_team.threshold_conceded_gt,
                    cfg.blue_team.threshold_net_lt,
                    cfg.blue_team.formula,
                )
            )
        if cfg.missed_penalty.enabled:
            self.rules.append(MissedPenaltyBonus(cfg.missed_penalty.per_event))

    def run(self, ctx: BonusContext) -> list[Award]:
        out = []
        for r in self.rules:
            out.extend(r.compute(ctx))
        return out
