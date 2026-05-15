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

## SQLite setup

### Quick start

```bash
# 1. Install dependencies (conda env must already exist — see environment.yml)
make env-update

# 2. Create the database file and apply the full schema
make db-init           # creates fmlwc.db
make db-init DB=my.db  # custom path

# 3. Open the interactive SQLite shell
make db-shell          # opens fmlwc.db
make db-shell DB=my.db # custom path

# Reset (drop and recreate) an existing database
make db-reset
```

The `sqlite3` binary used is the one bundled in the conda env
(`anaconda3/envs/fmlwc/bin/sqlite3`). If you want to call it directly:

```bash
~/anaconda3/envs/fmlwc/bin/sqlite3 fmlwc.db
```

For in-memory use (tests / demos) pass `"sqlite:///:memory:"` to
`make_engine` instead of a file path.

### Shell usage

Once inside the `sqlite3` shell, useful dot-commands:

```
.tables                   -- list all tables
.schema match_events      -- DDL for one table
.headers on               -- show column names in results
.mode column              -- align columns
.mode box                 -- box-drawing borders (sqlite3 ≥ 3.37)
.quit                     -- exit
```

Common queries for this schema:

```sql
-- All managers and their current balances
SELECT id, display_name, balance FROM managers ORDER BY balance DESC;

-- Active roster for manager 1
SELECT p.name, p.position, p.real_team, r.acquired_price
FROM roster_entries r
JOIN players p ON p.id = r.player_id
WHERE r.manager_id = 1 AND r.released_at IS NULL;

-- Events for gameweek 1
SELECT p.name, e.event_type, e.minute, e.is_extra_time, e.is_shootout
FROM match_events e
JOIN players p ON p.id = e.player_id
WHERE e.gameweek_id = 1
ORDER BY e.minute;

-- Group standings snapshot (goals and points per manager)
SELECT m.display_name, pa.goals, pa.assists, pa.yellows, pa.reds
FROM player_athletics pa
JOIN players p ON p.id = pa.player_id
JOIN roster_entries r ON r.player_id = p.id AND r.released_at IS NULL
JOIN managers m ON m.id = r.manager_id
ORDER BY pa.goals DESC;

-- Per-manager team aggregate
SELECT m.display_name, ms.goals, ms.assists, ms.reds
FROM manager_stats ms
JOIN managers m ON m.id = ms.manager_id
ORDER BY ms.goals DESC;

-- Which players contributed to manager 1's stats and when
SELECT p.name, mpa.goals, mpa.assists, mpa.yellows
FROM manager_player_athletics mpa
JOIN players p ON p.id = mpa.player_id
WHERE mpa.manager_id = 1
ORDER BY mpa.goals DESC;

-- Fixture results for gameweek 1
SELECT hm.display_name AS home, am.display_name AS away,
       r.home_goals, r.away_goals, r.outcome
FROM match_results r
JOIN fixtures f ON f.id = r.fixture_id
JOIN managers hm ON hm.id = f.home_manager_id
JOIN managers am ON am.id = f.away_manager_id
WHERE f.gameweek_id = 1;
```

### Database file location

| Path | Purpose |
|---|---|
| `fmlwc.db` | Default dev/demo database |
| `sqlite:///:memory:` | Unit tests and one-shot scripts |
| any path via env var | `make_engine(os.environ["FMLWC_DB_URL"])` |

There is no migration tooling yet — schema changes require recreating the
file. Production use should adopt Alembic before storing real data.

### Tables created

| Table | Model | Description |
|---|---|---|
| `managers` | `Manager` | Participants; holds current balance |
| `players` | `Player` | Real-world footballers |
| `roster_entries` | `RosterEntry` | Player↔manager ownership history |
| `auction_rounds` | `AuctionRound` | Sealed-bid round metadata |
| `submissions` | `Submission` | One bid sheet per manager per round |
| `bids` | `Bid` | Individual bid rows with cascade status |
| `auction_results` | `AuctionResult` | Final award per player per round |
| `transfer_windows` | `TransferWindow` | Free-sign / trade periods |
| `free_signs` | `FreeSign` | Free-agent signings within a window |
| `trades` | `Trade` / `TradeLeg` | Player swap agreements |
| `releases` | `Release` | Voluntary roster releases |
| `eligibility_records` | `EligibilityRecord` | Signing restrictions |
| `gameweeks` | `Gameweek` | Match rounds with phase + status (`PENDING/LIVE/FINALIZED`) |
| `fixtures` | `Fixture` | A single home-vs-away match within a gameweek |
| `lineups` | `Lineup` | Manager's submitted starters (JSON) + PK order |
| `match_events` | `MatchEvent` | Live events keyed by `(gameweek_id, player_id)` |
| `match_results` | `MatchResult` | Locked score + outcome per fixture |
| `bonus_awards` | `BonusAward` | Assist/red-card/blue-team/missed-penalty awards |
| `player_athletics` | `PlayerAthletics` | Career stats per player (season total) |
| `manager_stats` | `ManagerStats` | Team aggregate stats per manager |
| `manager_player_athletics` | `ManagerPlayerAthletics` | Per-player breakdown within each manager's historical roster |
| `roster_snapshots` | `RosterSnapshot` | Knockout pre-match roster freeze |
| `picks` | `Pick` | Knockout-winner player picks |
| `injury_adjustments` | `InjuryAdjustment` | Injury-grant roster exceptions |

### Connecting from a script

```python
from fmlwc.persistence.db import make_engine, make_session_factory, session_scope
from fmlwc.persistence.sql_repos import SqlManagerRepo, SqlGameweekRepo  # etc.

engine  = make_engine("sqlite:///fmlwc.db")
factory = make_session_factory(engine)

with session_scope(factory) as session:
    managers = SqlManagerRepo(session).list_active()
```

`session_scope` commits on success and rolls back on any exception —
always use it instead of managing the session manually.

### SQLite pragmas applied automatically

`make_engine` sets two pragmas on every new SQLite connection:

| Pragma | Value | Reason |
|---|---|---|
| `foreign_keys` | `ON` | Enforce FK constraints (SQLite ignores them by default) |
| `journal_mode` | `WAL` | Concurrent reads while a write is in progress |

## Round setup

Before live events can be recorded, the gameweek and its fixtures must exist in
the database and lineups must be submitted.

### 1. Open the gameweek

```python
from fmlwc.core.enums import GameweekPhase, GameweekStatus
from fmlwc.persistence.sql_repos import SqlGameweekRepo

with session_scope(factory) as session:
    gameweeks = SqlGameweekRepo(session)
    gw_id = gameweeks.create(
        index=1,
        phase=GameweekPhase.GROUP,
        lineup_deadline=deadline,   # naive UTC datetime
    )
    gameweeks.set_status(gw_id, GameweekStatus.LIVE)
```

`create` inserts a `PENDING` gameweek and returns its id. Call `set_status`
to advance it to `LIVE` once the real matches kick off.

### 2. Persist fixtures

```python
from fmlwc.persistence.sql_repos import SqlFixtureRepo

with session_scope(factory) as session:
    fixtures = SqlFixtureRepo(session)
    for spec in scheduler.group_stage_fixtures(groups)[round_index]:
        fixtures.create(
            gw_id,
            spec.home_manager_id,
            spec.away_manager_id,
            group_letter=spec.group_letter,
        )
```

Pass `bracket_slot` instead of `group_letter` for knockout rounds.

### 3. Submit lineups

Lineups are validated first, then persisted as a list of
`{"player_id": int, "slot_position": str}` dicts — the serialised form of
`ValidatedLineup.accepted`.

```python
from fmlwc.persistence.sql_repos import SqlFixtureRepo
from fmlwc.domain.lineup.validator import LineupValidator

with session_scope(factory) as session:
    fixtures = SqlFixtureRepo(session)
    result = lineup_validator.validate(manager_id, raw_starters)
    fixtures.save_lineup(
        fixture_id,
        manager_id,
        starters=[
            {"player_id": s.player_id, "slot_position": s.slot_position.value}
            for s in result.accepted
        ],
        posted_at=now,
    )
```

Re-submitting before the deadline replaces the previous lineup.
The optional `pk_order` argument accepts a list of player ids for penalty
shootout resolution (knockout rounds only).

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
