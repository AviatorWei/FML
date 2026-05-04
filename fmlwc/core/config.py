"""Rule configuration loader.

Single source of truth: `config/rules.example.yaml`.
Loaded into a tree of frozen dataclasses (see `_config_types`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ._config_types import (
    AuctionCascadeConfig, AuctionConfig, AuctionRoundSpec,
    BlueTeamConfig, BonusesConfig, FlatBonusConfig, ValidGoalConfig,
    GroupStageConfig, InjuryConfig, KnockoutConfig, LineupConfig,
    ManagersConfig, MatchConfig, PkScoreConfig, PrizeBucketConfig,
    PrizesConfig, ReleaseConfig, RosterConfig, ScopeConfig,
    StorageConfig, TransferConfig, TransferWindowSpec,
)
from .enums import Position
from .exceptions import ConfigError


# --- helpers ---------------------------------------------------------------

def _require(d, key, path):
    if key not in d:
        raise ConfigError(f"missing required key '{key}' at {path or '<root>'}")
    return d[key]


def _as_int(value, path):
    if isinstance(value, bool):
        raise ConfigError(f"expected int at {path}, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip().lower().replace("_", "")
        if s.endswith("m"):
            try:
                return int(float(s[:-1]))
            except ValueError as e:
                raise ConfigError(f"invalid m-shorthand at {path}: {value!r}") from e
        try:
            return int(s)
        except ValueError as e:
            raise ConfigError(f"expected int at {path}, got {value!r}") from e
    raise ConfigError(f"expected int at {path}, got {type(value).__name__}")


def _as_float(value, path):
    if isinstance(value, bool):
        raise ConfigError(f"expected number at {path}, got bool")
    if isinstance(value, (int, float)):
        return float(value)
    raise ConfigError(f"expected number at {path}, got {type(value).__name__}")


def _as_bool(value, path):
    if isinstance(value, bool):
        return value
    raise ConfigError(f"expected bool at {path}, got {type(value).__name__}")


def _as_str(value, path):
    if isinstance(value, str):
        return value
    raise ConfigError(f"expected str at {path}, got {type(value).__name__}")


def _parse_position_map(raw, path):
    if not isinstance(raw, Mapping):
        raise ConfigError(f"expected mapping at {path}")
    out = {}
    for k, v in raw.items():
        try:
            pos = Position(k)
        except ValueError as e:
            raise ConfigError(f"unknown position key {k!r} at {path}") from e
        out[pos] = _as_int(v, f"{path}.{k}")
    return out


def _parse_position_list(raw, path):
    if not isinstance(raw, list):
        raise ConfigError(f"expected list at {path}")
    out = []
    for i, item in enumerate(raw):
        try:
            out.append(Position(item))
        except ValueError as e:
            raise ConfigError(f"unknown position {item!r} at {path}[{i}]") from e
    return out


def _parse_dt(value, path):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ConfigError(f"invalid datetime at {path}: {value!r}") from e
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ConfigError(f"expected datetime/str at {path}, got {type(value).__name__}")


# --- parsers per section ---------------------------------------------------

def _parse_scope(r):
    return ScopeConfig(
        name=_as_str(_require(r, "name", "scope"), "scope.name"),
        short=_as_str(_require(r, "short", "scope"), "scope.short"),
        timezone=_as_str(_require(r, "timezone", "scope"), "scope.timezone"),
    )


def _parse_managers(r):
    return ManagersConfig(
        count=_as_int(_require(r, "count", "managers"), "managers.count"),
        initial_budget=_as_int(_require(r, "initial_budget", "managers"), "managers.initial_budget"),
        groups=_as_int(_require(r, "groups", "managers"), "managers.groups"),
    )


def _parse_roster(r):
    return RosterConfig(
        total_cap=_as_int(_require(r, "total_cap", "roster"), "roster.total_cap"),
        position_caps=_parse_position_map(_require(r, "position_caps", "roster"), "roster.position_caps"),
    )


def _parse_auction(r):
    rounds_raw = _require(r, "rounds", "auction")
    if not isinstance(rounds_raw, list):
        raise ConfigError("auction.rounds must be a list")
    rounds = []
    for i, rr in enumerate(rounds_raw):
        rounds.append(AuctionRoundSpec(
            index=_as_int(_require(rr, "index", f"auction.rounds[{i}]"), f"auction.rounds[{i}].index"),
            opens_at=_parse_dt(_require(rr, "opens_at", f"auction.rounds[{i}]"), f"auction.rounds[{i}].opens_at"),
            closes_at=_parse_dt(_require(rr, "closes_at", f"auction.rounds[{i}]"), f"auction.rounds[{i}].closes_at"),
        ))
    cas = _require(r, "cascade", "auction")
    cascade = AuctionCascadeConfig(
        position_priority=_parse_position_list(_require(cas, "position_priority", "auction.cascade"), "auction.cascade.position_priority"),
        invalidate_tie_priority=_parse_position_list(_require(cas, "invalidate_tie_priority", "auction.cascade"), "auction.cascade.invalidate_tie_priority"),
        invalidate_tie_within_pos=_as_str(_require(cas, "invalidate_tie_within_pos", "auction.cascade"), "auction.cascade.invalidate_tie_within_pos"),
    )
    cr = r.get("conditional_release", {}) if isinstance(r, dict) else {}
    conditional_release_enabled = _as_bool(
        cr.get("enabled", False),
        "auction.conditional_release.enabled",
    )
    return AuctionConfig(
        rounds=rounds,
        min_bid=_as_int(_require(r, "min_bid", "auction"), "auction.min_bid"),
        tiebreaker=_as_str(_require(r, "tiebreaker", "auction"), "auction.tiebreaker"),
        cascade=cascade,
        collusion_block_next_window=_as_bool(_require(r, "collusion_block_next_window", "auction"), "auction.collusion_block_next_window"),
        conditional_release_enabled=conditional_release_enabled,
    )


def _parse_transfer(r):
    windows_raw = _require(r, "windows", "transfer")
    windows = []
    for i, w in enumerate(windows_raw):
        windows.append(TransferWindowSpec(
            opens_at=_parse_dt(_require(w, "opens_at", f"transfer.windows[{i}]"), f"transfer.windows[{i}].opens_at"),
            closes_at=_parse_dt(_require(w, "closes_at", f"transfer.windows[{i}]"), f"transfer.windows[{i}].closes_at"),
            free_sign_period_seconds=_as_int(_require(w, "free_sign_period_seconds", f"transfer.windows[{i}]"), f"transfer.windows[{i}].free_sign_period_seconds"),
        ))
    trades = _require(r, "trades", "transfer")
    return TransferConfig(
        windows=windows,
        free_sign_fee=_as_int(_require(r, "free_sign_fee", "transfer"), "transfer.free_sign_fee"),
        revoke_window_seconds=_as_int(_require(r, "revoke_window_seconds", "transfer"), "transfer.revoke_window_seconds"),
        trades_allow_cash=_as_bool(_require(trades, "allow_cash", "transfer.trades"), "transfer.trades.allow_cash"),
        trades_require_counterparty_accept=_as_bool(_require(trades, "require_counterparty_accept", "transfer.trades"), "transfer.trades.require_counterparty_accept"),
        same_window_block_after_free_sign=_as_bool(_require(r, "same_window_block_after_free_sign", "transfer"), "transfer.same_window_block_after_free_sign"),
    )


def _parse_release(r):
    return ReleaseConfig(
        refund=_as_int(_require(r, "refund", "release"), "release.refund"),
        releaser_lifetime_block=_as_bool(_require(r, "releaser_lifetime_block", "release"), "release.releaser_lifetime_block"),
        revoke_window_seconds=_as_int(_require(r, "revoke_window_seconds", "release"), "release.revoke_window_seconds"),
    )


def _parse_lineup(r):
    bs_raw = _require(r, "backward_substitution", "lineup")
    bs = {}
    for k, v in bs_raw.items():
        try:
            pos = Position(k)
        except ValueError as e:
            raise ConfigError(f"unknown position {k!r} at lineup.backward_substitution") from e
        bs[pos] = _parse_position_list(v, f"lineup.backward_substitution.{k}")
    return LineupConfig(
        starters_min=_as_int(_require(r, "starters_min", "lineup"), "lineup.starters_min"),
        starters_max=_as_int(_require(r, "starters_max", "lineup"), "lineup.starters_max"),
        appearance_caps=_parse_position_map(_require(r, "appearance_caps", "lineup"), "lineup.appearance_caps"),
        must_have_positions=_parse_position_list(_require(r, "must_have_positions", "lineup"), "lineup.must_have_positions"),
        backward_substitution=bs,
        default_strategy=_as_str(_require(r, "default_strategy", "lineup"), "lineup.default_strategy"),
        misplaced_player_action=_as_str(_require(r, "misplaced_player_action", "lineup"), "lineup.misplaced_player_action"),
    )


def _parse_match(r):
    gs = _require(r, "group_stage", "match")
    pts = _require(gs, "points", "match.group_stage")
    if not isinstance(pts, Mapping):
        raise ConfigError("match.group_stage.points must be a mapping")
    points = {str(k): _as_int(v, f"match.group_stage.points.{k}") for k, v in pts.items()}
    gscfg = GroupStageConfig(
        rounds=_as_int(_require(gs, "rounds", "match.group_stage"), "match.group_stage.rounds"),
        points=points,
        tiebreak_order=[_as_str(t, "match.group_stage.tiebreak_order") for t in _require(gs, "tiebreak_order", "match.group_stage")],
    )
    ko = _require(r, "knockout", "match")
    pk_raw = _require(ko, "pk_score", "match.knockout")
    pk = PkScoreConfig(
        goal=_as_float(_require(pk_raw, "goal", "match.knockout.pk_score"), "match.knockout.pk_score.goal"),
        assist=_as_float(_require(pk_raw, "assist", "match.knockout.pk_score"), "match.knockout.pk_score.assist"),
        yellow=_as_float(_require(pk_raw, "yellow", "match.knockout.pk_score"), "match.knockout.pk_score.yellow"),
        second_yellow_red=_as_float(_require(pk_raw, "second_yellow_red", "match.knockout.pk_score"), "match.knockout.pk_score.second_yellow_red"),
        red=_as_float(_require(pk_raw, "red", "match.knockout.pk_score"), "match.knockout.pk_score.red"),
        real_advance_bonus=_as_float(_require(pk_raw, "real_advance_bonus", "match.knockout.pk_score"), "match.knockout.pk_score.real_advance_bonus"),
    )
    kocfg = KnockoutConfig(
        bracket=_as_str(_require(ko, "bracket", "match.knockout"), "match.knockout.bracket"),
        advance_priority=[_as_str(p, "match.knockout.advance_priority") for p in _require(ko, "advance_priority", "match.knockout")],
        pk_score=pk,
        pk_default_order=_parse_position_list(_require(ko, "pk_default_order", "match.knockout"), "match.knockout.pk_default_order"),
        enable_pick=_as_bool(_require(ko, "enable_pick", "match.knockout"), "match.knockout.enable_pick"),
        pick_deadline_seconds=_as_int(_require(ko, "pick_deadline_seconds", "match.knockout"), "match.knockout.pick_deadline_seconds"),
    )
    return MatchConfig(group_stage=gscfg, knockout=kocfg)


def _parse_valid_goal(r):
    return ValidGoalConfig(
        count_event_types=[_as_str(t, "valid_goal.count_event_types") for t in _require(r, "count_event_types", "valid_goal")],
        exclude_penalty_shootout=_as_bool(_require(r, "exclude_penalty_shootout", "valid_goal"), "valid_goal.exclude_penalty_shootout"),
        scope_minutes=_as_str(_require(r, "scope_minutes", "valid_goal"), "valid_goal.scope_minutes"),
    )


def _parse_flat_bonus(r, path):
    return FlatBonusConfig(
        enabled=_as_bool(_require(r, "enabled", path), f"{path}.enabled"),
        per_event=_as_int(_require(r, "per_event", path), f"{path}.per_event"),
    )


def _parse_bonuses(r):
    bt = _require(r, "blue_team", "bonuses")
    blue = BlueTeamConfig(
        enabled=_as_bool(_require(bt, "enabled", "bonuses.blue_team"), "bonuses.blue_team.enabled"),
        threshold_conceded_gt=_as_int(_require(bt, "threshold_conceded_gt", "bonuses.blue_team"), "bonuses.blue_team.threshold_conceded_gt"),
        threshold_net_lt=_as_int(_require(bt, "threshold_net_lt", "bonuses.blue_team"), "bonuses.blue_team.threshold_net_lt"),
        formula=_as_str(_require(bt, "formula", "bonuses.blue_team"), "bonuses.blue_team.formula"),
    )
    return BonusesConfig(
        assist=_parse_flat_bonus(_require(r, "assist", "bonuses"), "bonuses.assist"),
        red_card=_parse_flat_bonus(_require(r, "red_card", "bonuses"), "bonuses.red_card"),
        blue_team=blue,
        missed_penalty=_parse_flat_bonus(_require(r, "missed_penalty", "bonuses"), "bonuses.missed_penalty"),
    )


def _parse_prize_bucket(r, path):
    return PrizeBucketConfig(
        extra=_as_int(_require(r, "extra", path), f"{path}.extra"),
        weight_formula=_as_str(_require(r, "weight_formula", path), f"{path}.weight_formula"),
    )


def _parse_prizes(r):
    return PrizesConfig(
        qualify=_parse_prize_bucket(_require(r, "qualify", "prizes"), "prizes.qualify"),
        advance=_parse_prize_bucket(_require(r, "advance", "prizes"), "prizes.advance"),
        rounding=_as_str(_require(r, "rounding", "prizes"), "prizes.rounding"),
    )


def _parse_injury(r):
    return InjuryConfig(
        enabled=_as_bool(_require(r, "enabled", "injury"), "injury.enabled"),
        refund_last_signing_fee=_as_bool(_require(r, "refund_last_signing_fee", "injury"), "injury.refund_last_signing_fee"),
        grant_extra_free_sign_after_window=_as_bool(_require(r, "grant_extra_free_sign_after_window", "injury"), "injury.grant_extra_free_sign_after_window"),
        gk_zero_balance_grant=_as_int(_require(r, "gk_zero_balance_grant", "injury"), "injury.gk_zero_balance_grant"),
    )


def _parse_storage(r):
    return StorageConfig(
        driver=_as_str(_require(r, "driver", "storage"), "storage.driver"),
        url=_as_str(_require(r, "url", "storage"), "storage.url"),
        echo=_as_bool(_require(r, "echo", "storage"), "storage.echo"),
    )


# --- root ------------------------------------------------------------------

@dataclass(frozen=True)
class GameRules:
    """Root configuration object."""

    scope: ScopeConfig
    managers: ManagersConfig
    roster: RosterConfig
    auction: AuctionConfig
    transfer: TransferConfig
    release: ReleaseConfig
    lineup: LineupConfig
    match: MatchConfig
    valid_goal: ValidGoalConfig
    bonuses: BonusesConfig
    prizes: PrizesConfig
    injury: InjuryConfig
    storage: StorageConfig

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, Mapping):
            raise ConfigError(f"top-level config must be a mapping, got {type(raw).__name__}")
        return cls(
            scope=_parse_scope(_require(raw, "scope", "")),
            managers=_parse_managers(_require(raw, "managers", "")),
            roster=_parse_roster(_require(raw, "roster", "")),
            auction=_parse_auction(_require(raw, "auction", "")),
            transfer=_parse_transfer(_require(raw, "transfer", "")),
            release=_parse_release(_require(raw, "release", "")),
            lineup=_parse_lineup(_require(raw, "lineup", "")),
            match=_parse_match(_require(raw, "match", "")),
            valid_goal=_parse_valid_goal(_require(raw, "valid_goal", "")),
            bonuses=_parse_bonuses(_require(raw, "bonuses", "")),
            prizes=_parse_prizes(_require(raw, "prizes", "")),
            injury=_parse_injury(_require(raw, "injury", "")),
            storage=_parse_storage(_require(raw, "storage", "")),
        )

    @classmethod
    def from_yaml(cls, path):
        try:
            import yaml
        except ImportError as e:
            raise ConfigError("PyYAML not installed") from e
        text = Path(path).read_text(encoding="utf-8")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML parse error in {path}: {e}") from e
        return cls.from_dict(raw)
