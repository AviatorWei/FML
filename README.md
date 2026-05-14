# FMLWC — Fantasy Football League With Cash

规则可配置的范特西足球游戏后端。当前版本对齐 FME-2021 (Euro 2020/2021) 规则，但所有数值/开关都通过 YAML 注入，可适配欧洲杯、世界杯、英超联赛等任意 scope。

## 当前状态

`v0.1` — **设计 + 模块骨架**。所有 service 方法体为 `TODO`/`raise NotImplementedError`。骨架既是实现路线图，也是审阅规则覆盖完整度的检查清单。

## 文件入口

| 文件 | 作用 |
|---|---|
| `DESIGN.md` | 架构与算法说明（必读） |
| `RULES.md` | FME-2021 规则原文（事实标准） |
| `config/rules.example.yaml` | 规则配置示例，单一事实数值源 |
| `fmlwc/` | 引擎包 |
| `scripts/demo_cycle.py` | 演示一个迷你赛季的完整流程 |
| `tests/` | 测试占位（建议优先补足关键算法的单测） |

## 模块速览（三层结构）

```
fmlwc/
├── core/                       基础内核（无外部依赖）
│   ├── enums.py                Position / Phase / BidStatus / ...
│   ├── exceptions.py           异常树
│   └── config.py               GameRules (YAML 强类型加载)
├── persistence/                存储层 (依赖 core)
│   ├── base.py                 DeclarativeBase
│   ├── db.py                   make_engine / session_scope
│   ├── repositories.py         Protocol + SQL 实现
│   └── models/                 ORM 按聚合分文件
│       ├── people.py           Manager / Player / RosterEntry
│       ├── auction.py          AuctionRound / Submission / Bid / Result
│       ├── transfer.py         Window / FreeSign / Trade / TradeLeg / Release
│       ├── eligibility.py      EligibilityRecord
│       ├── match.py            Gameweek / Fixture / Lineup / Event / Result / Bonus
│       ├── knockout.py         RosterSnapshot / Pick
│       └── injury.py           InjuryAdjustment
└── domain/                     业务层 (依赖 core + persistence)
    ├── eligibility.py          签约闸门（单文件，跨域使用）
    ├── auction/                暗标 (4 文件: bids/cascade/tiebreaker/service)
    ├── transfer/               转会 (3 文件: free_sign/trade/release)
    ├── lineup/                 阵容 (2 文件: validator/defaults)
    ├── match/                  比赛 (7 文件: events/scoring/bonuses/...)
    ├── prize.py                出线奖+晋级奖（单文件）
    ├── injury.py               伤兵特例（单文件）
    └── season.py               状态机编排（单文件）
```

依赖方向：`domain → persistence → core`，反向不允许。
分包策略：domain 下文件多于 1 个时建子包，否则保留为单文件，避免 `__init__.py` 样板代码。

## 后续

1. 填充 service 方法体（建议次序：`config` → `eligibility` → `auction.cascade` → `auction.service` → `lineup.validator` → `match.scoring` → 其他）。
2. 补关键算法的 pytest 单测（见 `tests/test_placeholder.py` 的优先级清单）。
3. 实装真实事件导入器（UEFA/Whoscored 适配器）。
4. 用 Alembic 替换 `db.create_all`。

## Match event interface

The entry point for live match management is `RoundService` in
`fmlwc.domain.match.round`. It exposes three operations:

| Method | When to call |
|---|---|
| `add_event(gameweek_id, player_id, event_type, ...)` | Any time during a LIVE gameweek |
| `remove_event(gameweek_id, event_id)` | Correct a mistake while still LIVE |
| `finalize_gameweek(gameweek_id)` | Lock the round, write results + stats |

### Wiring up the service

```python
from fmlwc.core.config import GameRules
from fmlwc.core.enums import GameweekStatus, RealEventType
from fmlwc.persistence.db import create_all, make_engine, make_session_factory, session_scope
from fmlwc.persistence.repositories import (
    SqlAthleticsRepo,
    SqlFixtureRepo,
    SqlGameweekRepo,
    SqlManagerRepo,
    SqlMatchEventRepo,
)
from fmlwc.domain.match.round import RoundService

rules = GameRules.from_yaml("config/rules.example.yaml")

engine = make_engine("sqlite:///fmlwc.db")
create_all(engine)                          # dev/demo only — use Alembic in production
factory = make_session_factory(engine)

with session_scope(factory) as session:
    service = RoundService(
        rules=rules,
        gameweeks=SqlGameweekRepo(session),
        fixtures=SqlFixtureRepo(session),
        events=SqlMatchEventRepo(session),
        athletics=SqlAthleticsRepo(session),
        managers=SqlManagerRepo(session),
    )
```

### Adding events during a live gameweek

`add_event` returns the new `event_id` so you can retract it if needed.
The gameweek must already be in `LIVE` status (set via `GameweekRepo.set_status`);
calling on a `PENDING` or `FINALIZED` gameweek raises `MatchError`.

```python
with session_scope(factory) as session:
    svc = RoundService(rules=rules,
                       gameweeks=SqlGameweekRepo(session),
                       fixtures=SqlFixtureRepo(session),
                       events=SqlMatchEventRepo(session),
                       athletics=SqlAthleticsRepo(session),
                       managers=SqlManagerRepo(session))

    gameweek_id = 1

    # Regular goal by player 42 in minute 67
    goal_id = svc.add_event(gameweek_id, player_id=42,
                            event_type=RealEventType.GOAL, minute=67)

    # Assist by player 7 (same move)
    svc.add_event(gameweek_id, player_id=7,
                  event_type=RealEventType.ASSIST, minute=67)

    # Extra-time goal — flag it so scoring can distinguish if needed
    svc.add_event(gameweek_id, player_id=99,
                  event_type=RealEventType.GOAL, minute=104, is_extra_time=True)

    # Penalty shootout goal — excluded from valid-goal count by default
    svc.add_event(gameweek_id, player_id=42,
                  event_type=RealEventType.GOAL, is_shootout=True)
```

Available `RealEventType` values:

| Value | Counts as valid goal? | Notes |
|---|---|---|
| `GOAL` | yes | Regular or extra-time |
| `OWN_GOAL` | yes | Credited to the scorer's own team |
| `SAVED_PENALTY_BY_GK` | yes | +1 for the keeper's team |
| `MISSED_PENALTY` | no | Triggers `MissedPenaltyBonus` |
| `ASSIST` | no | Triggers `AssistBonus` |
| `YELLOW` | no | PK scoring input |
| `SECOND_YELLOW_RED` | no | PK scoring input |
| `RED` | no | Triggers `RedCardBonus`, PK scoring input |

### Removing a mistaken event

Pass the `event_id` returned by `add_event`. Only allowed while the
gameweek is `LIVE`.

```python
with session_scope(factory) as session:
    svc = RoundService(...)

    # VAR overturns the goal — retract it
    svc.remove_event(gameweek_id=1, event_id=goal_id)
```

### Finalizing the gameweek

Call once all events have been entered and verified. This is the only
write that cannot be undone.

```python
with session_scope(factory) as session:
    svc = RoundService(...)
    svc.finalize_gameweek(gameweek_id=1)
```

What happens internally:

1. **Fixture scores** — `ValidGoalCalculator` runs per fixture using the
   submitted lineups as the starter filter. Results are written to
   `match_results`.
2. **Bonuses** — `BonusEngine` computes assist / red-card / blue-team /
   missed-penalty awards and credits each manager's balance.
3. **Player career stats** — `PlayerAthletics` is incremented for every
   starter event (goals, assists, cards). Reflects the player's total
   regardless of transfers.
4. **Team aggregate** — `ManagerStats` is incremented with the same
   events, attributed to the manager who fielded the player in *this*
   gameweek's lineup, not the current owner.
5. **Per-player team breakdown** — `ManagerPlayerAthletics`
   `(manager_id, player_id)` is incremented, giving a per-player
   breakdown within each manager's historical roster.
6. Gameweek status is set to `FINALIZED`.

### Stats attribution example

```
Gameweek 1 — player A on Manager1's lineup, scores 2 goals
Gameweek 3 — player A transferred to Manager2, scores 1 goal

After finalize_gameweek(3):

PlayerAthletics      player_A           goals = 3
ManagerStats         manager_1          goals = 2
ManagerStats         manager_2          goals = 1
ManagerPlayerAthletics (manager_1, player_A)  goals = 2
ManagerPlayerAthletics (manager_2, player_A)  goals = 1
```

## 参考

- [`RULES.md`](./RULES.md) — FME-2021 规则原文
- [`DESIGN.md`](./DESIGN.md) — 架构说明
- [SQLAlchemy 2.0 ORM](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- [Pydantic v2](https://docs.pydantic.dev/latest/)
- [Sealed-bid auction (Wikipedia)](https://en.wikipedia.org/wiki/Sealed-bid_auction)

## 货币单位约定

所有金额（玩家余额、bid 出价、自由签 fee、奖金、出线/晋级奖等）均以**百万欧元**为单位的整数存储。YAML/数据库里写 `600` = 6 亿欧。换言之，"10m" 在代码中表达为 `10`，不是 `10_000_000`。
