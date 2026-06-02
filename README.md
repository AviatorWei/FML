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

## 环境配置

### 安装 Conda（首次）

项目依赖 Anaconda/Miniconda。若尚未安装，从 [https://docs.anaconda.com/miniconda/](https://docs.anaconda.com/miniconda/) 下载对应平台的安装包，按提示完成安装后重开终端。

### 创建环境（首次）

```bash
conda env create -f environment.yml
```

这会创建名为 `fmlwc` 的环境，包含 Python 3.11 及所有依赖（SQLAlchemy 2.0、Pydantic v2、PyYAML、pytest、ruff、mypy 等）。

### 激活环境

```bash
conda activate fmlwc
```

若 `conda` 命令未找到（常见于首次安装后未重开终端），先初始化再激活：

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate fmlwc
```

激活后提示符前会出现 `(fmlwc)`，此时 `python` 指向环境内的 Python 3.11。

### 更新依赖

```bash
make env-update   # 等价于: conda env update -n fmlwc -f environment.yml --prune
```

### 不激活环境时直接运行

如果不想每次激活，可以用环境内的绝对路径：

```bash
~/anaconda3/envs/fmlwc/bin/python scripts/run_auction1.py
~/anaconda3/envs/fmlwc/bin/python -m pytest tests/
```

Makefile 的所有目标（`make test`、`make db-init` 等）已硬编码此路径，无需激活环境即可使用。

---

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

## 球员列表初始化

在拍卖开始前，`players` 表需要用真实球员数据初始化。
`scripts/generate_player_list.py` 负责从 Transfermarkt 球队阵容页爬取数据并写入数据库；
爬虫核心逻辑在 `fmlwc/io/player_list_generator.py` 中，HTTP + HTML 解析部分留为 stub，可按需替换。

### 快速上手

```bash
# 查看帮助
python scripts/generate_player_list.py --help

# 干跑（仅打印，不写库）— 先跑这个确认 stub 实现后数据正确
python scripts/generate_player_list.py --dry-run

# 顺序 ID（1, 2, 3 …），写入默认 fmlwc.db
python scripts/generate_player_list.py --id-mode seq

# 从 Transfermarkt URL 提取 ID，写入自定义路径
python scripts/generate_player_list.py --id-mode url --db path/to.db

# 只爬部分球队
python scripts/generate_player_list.py --teams GER,ENG,FRA --dry-run

# 顺序 ID 从 1001 开始（如需为新赛季追加球员时避免冲突）
python scripts/generate_player_list.py --id-mode seq --seq-start 1001
```

### ID 策略

| `--id-mode` | 说明 | 适用场景 |
|---|---|---|
| `seq`（默认） | 按 (球队顺序, 号码, 姓名) 排序后，从 `--seq-start`（默认 1）开始连续编号 | 与现有竞标 xlsx 文件中的短号码（1号、2号…）保持一致 |
| `url` | 从 Transfermarkt 球员主页 URL 中提取数字 ID（`/spieler/17259` → `17259`） | 需要与外部数据源 ID 对齐时使用；ID 跨赛季稳定唯一 |

### 实现爬虫

`_scrape_team_page` 函数目前为 stub，调用时抛出 `NotImplementedError`。
打开 `fmlwc/io/player_list_generator.py`，将函数体替换为真实实现（函数内注释中已提供 `requests` + `BeautifulSoup` 的参考片段）：

```python
# fmlwc/io/player_list_generator.py — _scrape_team_page 示例骨架
import requests
from bs4 import BeautifulSoup

def _scrape_team_page(config: TeamConfig, http_session=None) -> list[RawPlayer]:
    session = http_session or requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FMLWC-scraper/0.1)"}
    resp = session.get(config.squad_url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    players = []
    for row in soup.select("table.items tbody tr.odd, table.items tbody tr.even"):
        name_tag = row.select_one("td.hauptlink a")
        pos_tag  = row.select_one("td.posrela")
        no_tag   = row.select_one("td.rn_nummer")
        val_tag  = row.select_one("td.rechts")
        if not name_tag:
            continue
        players.append(RawPlayer(
            name=name_tag.get_text(strip=True),
            jersey_no=int(no_tag.get_text(strip=True)) if no_tag else None,
            position_raw=pos_tag.get_text(strip=True) if pos_tag else "",
            real_team=config.code,
            market_value_eur_m=_parse_market_value(val_tag.get_text(strip=True) if val_tag else ""),
            profile_url="https://www.transfermarkt.com" + name_tag["href"],
        ))
    return players
```

### 位置映射

Transfermarkt 使用英文全称位置标签；`normalise_position()` 将其统一映射到引擎内部的 `G / D / M / F`。

| Transfermarkt 标签 | 缩写 | FMLWC |
|---|---|---|
| Goalkeeper | GK | **G** |
| Centre-Back, Left-Back, Right-Back | CB, LB, RB | **D** |
| Central Midfield, Defensive Midfield, Attacking Midfield, Left/Right Midfield | CM, CDM, CAM, LM, RM | **M** |
| Centre-Forward, Left Winger, Right Winger, Second Striker | CF, LW, RW, SS | **F** |
| G, D, M, F（已是引擎格式） | — | 直传 |

无法识别的位置标签默认映射为 **M**（中场），不会中断导入；
若爬取到陌生标签，建议在 `_POSITION_MAP` 中补充对应条目。

### 注入目标

| 目标 | 函数 | 适用场景 |
|---|---|---|
| SQLite 数据库 | `inject_into_session(players, session)` | 生产/演示，调用方负责 `session.commit()` |
| `FakePlayerRepo` | `inject_into_fake_repo(players, repo)` | 测试和 `run_auction*.py` 演示脚本 |

`inject_into_session` 使用 merge-or-insert 策略：相同 id 的行会原地更新，不存在则插入。
重复运行脚本是安全的（幂等）。

### Euro 2020 球队列表

`EURO_2020_TEAMS` 常量预置了 24 支参赛队的 Transfermarkt 阵容页 URL。
如需为其他赛事生成球员列表，传入自定义 `list[TeamConfig]` 即可：

```python
from fmlwc.io.player_list_generator import TeamConfig, PlayerListGenerator, IdMode

my_teams = [
    TeamConfig("ENG", "https://www.transfermarkt.com/england/kader/verein/3/saison_id/2022"),
    TeamConfig("FRA", "https://www.transfermarkt.com/frankreich/kader/verein/3377/saison_id/2022"),
]
generator = PlayerListGenerator(my_teams, id_mode=IdMode.SEQUENTIAL)
players = generator.generate()   # list[tuple[int, RawPlayer]]
```

## 暗标拍卖（Sealed-bid Auction）

每轮拍卖由竞标 xlsx 文件驱动。所有 xlsx 读入后送入 `AuctionService`，引擎完成验证 → Cascade → 逐球员决标 → 阵容更新。

### 快速验证（对比历史结果）

`scripts/run_auction1.py` 读取 `example/bids-1/` 目录下所有 xlsx，用内存 fake repos 跑完第一轮，并与 `example/1轮暗标公示.txt` / `1轮暗标后阵容.txt` 逐条比对：

```bash
python scripts/run_auction1.py
```

输出示例（全部匹配时）：

```
[load] read 16 submission files from example/bids-1
[setup] found 108 unique players across all bids
[setup] managers (16): ['ALB', 'CZE', ...]
[submit] submitted 16 bid sheets
[resolve] 108 awards, 0 cascade-invalidated, total spend 4336m

======================================================================
ANNOUNCEMENT COMPARISON
======================================================================
  OK — all bid lines match (player_id, manager_code, rank, amount)

======================================================================
ROSTER COMPARISON
======================================================================
  OK — all roster entries match (player, balance, price)

======================================================================
SUMMARY
======================================================================
  PASS — auction output matches expected for round 1
```

脚本最后无论是否匹配，均打印完整的**暗标公示**和**赛后阵容**供人工审阅。

### 竞标 xlsx 格式

每支队伍一个文件，命名规则 `FME_<年>_Bid<轮次>_<队伍代码>.xlsx`，活动 Sheet 的前六列为：

| 列 | 含义 | 说明 |
|---|---|---|
| A — Order | `rank_in_position` | 正整数，越小越优先；同队内同位置可重复 |
| B — Price | 出价（百万欧元） | 整数，最低 10m |
| C — ID | 球员 ID | 与 `players` 表 `id` 一致 |
| D — Name | 球员姓名 | 仅供阅读，不参与计算 |
| E — Team | 真实球队代码 | 仅供阅读 |
| F — Pos | 位置（G/D/M/F） | 仅供阅读；引擎以数据库中的位置为准 |

**有效行**：A 列为非零整数。A 列为空或 0 的行跳过（可用作备注行）。

xlsx 模板还有 G–J 列（余额汇总公式），引擎忽略。

### 流程说明

| 步骤 | 方法 | 说明 |
|---|---|---|
| 1. 开启轮次 | `auction.open_round(round_id)` | 状态置为 `OPEN`，可接收提交 |
| 2. 提交竞标 | `auction.submit(round_id, manager_id, raw_bids, received_at)` | 重复提交自动覆盖（rule 二.2） |
| 3. 关闭轮次 | `auction.close_round(round_id, at=close_time)` | 状态置为 `RESOLVING`，不再接收提交 |
| 4. 决标 | `auction.resolve(round_id, at=close_time)` | Cascade → 决标 → 余额扣除 → 阵容更新 |
| 5. 公示 | `auction.announcement_views(round_id)` | 返回所有参与决标的 bid 行（`AWARDED`/`LOST`） |

#### Cascade 规则（rule 二.4–二.5）

每位经理的竞标独立执行三轮 Cascade，直至所有约束均满足：

1. **位置人数上限**（F→M→D→G 顺序）：超出时，从该位置出价最高的 bid 开始作废
2. **总余额**：有效 bid 总出价 > 余额时，从所有位置出价最高的 bid 开始作废
3. **大名单总上限**：有效 bid 数 + 现有阵容 > 20 时，继续作废最高 bid

同价时的作废优先级：**F > M > D > G**，位置内再按 `rank_in_position` 升序（即数字小的先保留）。

#### 决标逻辑（rule 二.6）

每位球员只有一个获奖者，按以下键升序排列取最小（第一名获奖）：

```
(-出价, rank_in_position, 提交时间, deterministic_draw_seed)
```

即：出价越高越好；同价时 rank 越小越好；再同则按提交时间；最终由确定性随机种子打破平局。

### 运行脚本（写入 DB + 输出 txt）

`scripts/run_auction.py` 是面向生产/复盘的完整脚本：读取 xlsx → 写入 SQLite → 生成公示和阵容 txt 文件。

```bash
# 首次运行：自动从 xlsx 创建球员和经理记录，然后执行第 1 轮
python scripts/run_auction.py \
    --bids-dir example/bids-1 \
    --round 1 \
    --seed \
    --received-at "2026-06-01T20:00:00Z" \
    --closed-at   "2026-06-02T12:00:00Z"

# DB 已有球员/经理，仅执行拍卖
python scripts/run_auction.py --bids-dir example/bids-1 --round 1

# 自定义 DB 路径和输出目录
python scripts/run_auction.py \
    --bids-dir example/bids-1 --round 1 --seed \
    --db sqlite:///my.db --out-dir results/round1/

# 干跑：内存解算 + 写 txt，但不提交 DB
python scripts/run_auction.py --bids-dir example/bids-1 --round 1 --seed --dry-run
```

输出文件默认写入 `output/` 目录：

| 文件 | 内容 |
|---|---|
| `{N}轮暗标公示.txt` | 所有参与决标的 bid 行（AWARDED + LOST），格式与 `example/1轮暗标公示.txt` 一致 |
| `{N}轮暗标后阵容.txt` | 每位经理的阵容：人数、剩余资金、球员列表（按 G/D/M/F 位置排序） |

**防重复保护**：若该轮次（`--round`）已在 DB 中以 `CLOSED` 状态存在，脚本报错退出，避免重复结算。若需重跑，先 `make db-reset` 重置数据库。

**`--seed` 说明**：从 xlsx 数据自动 upsert 球员（id/姓名/球队/位置）和经理（display_name = 文件名代码，balance = initial_budget）。幂等，多次运行安全。不传 `--seed` 时，DB 中须已有 `display_name` 与 xlsx 文件名代码一致的经理记录。

### 程序化调用

```python
from datetime import datetime, timezone
from fmlwc.domain.auction.service import AuctionService
from fmlwc.io.xlsx_bid_reader import XlsxBidReader
from pathlib import Path

# -- 读入 xlsx --
reader = XlsxBidReader(Path("example/bids-1"))
submissions = reader.read_all()

# -- 提交 --
received_at = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
for sub in submissions:
    manager_id = code_to_id[sub.manager_code]
    auction.submit(round_id, manager_id, sub.to_raw_bids(manager_id), received_at)

# -- 决标 --
close_at = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
auction.close_round(round_id, at=close_at)
resolution = auction.resolve(round_id, at=close_at)
print(f"{len(resolution.awards)} awards, total {resolution.total_spend}m")

# -- 公示 --
from fmlwc.io.announcement import AuctionAnnouncementFormatter
views = auction.announcement_views(round_id)
print(AuctionAnnouncementFormatter().format(views))
```

### 公示格式

暗标公示按球员 ID 升序、同一球员按出价降序排列，每行格式为：

```
{rank}   {amount}m  {player_name:<20} {pos}  {real_team:<4}  {player_id}号 {manager_code}
```

只展示参与决标的 bid（`AWARDED` 和 `LOST`）；Cascade 作废或资格不符的 bid 不公开。

---

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

## 手动操作

赛季编排（Season orchestrator）尚未实现时，可通过以下命令手动完成各阶段操作。
所有脚本均从项目根目录运行；DB 路径和规则文件路径可通过 `--db` / `--rules` 覆盖。

### 前置：创建转会窗口

自由签必须在开放的转会窗口内进行。在 season orchestrator 就绪前可手动插入：

```bash
~/anaconda3/envs/fmlwc/bin/sqlite3 fmlwc.db \
  "INSERT INTO transfer_windows (opens_at, closes_at, free_sign_period_seconds, status)
   VALUES ('2026-06-03 00:00:00','2026-06-07 00:00:00',86400,'OPEN');"
```

| 字段 | 说明 |
|---|---|
| `opens_at` / `closes_at` | 窗口起止时间（SQLite 存储为无时区 UTC） |
| `free_sign_period_seconds` | 冷却期长度（秒）；86400 = 24 小时 |
| `status` | `OPEN` 立即生效；`PENDING` 暂不开放 |

---

### 自由签（rule 三）

`scripts/free_sign.py` 是自由签的完整操作入口，支持单笔和批量两种模式。

#### 生命周期

```
propose()    →  pending   (revoked=False, effective=False)
revoke()     →  cancelled (revoked=True,  fee not charged)
commit_due() →  effective (effective=True, balance -=10m, roster updated)
```

`commit_due` 需要在反悔窗口（默认 15 分钟）到期后调用，可手动触发或定时执行。

#### 单笔操作

```bash
# 提交一笔自由签（使用当前 UTC 时间）
python scripts/free_sign.py propose --manager 1 --player 42

# 指定时间戳（用于补录历史操作）
python scripts/free_sign.py propose --manager 1 --player 42 --at "2026-06-04T10:00:00Z"

# 反悔（必须在反悔窗口内）
python scripts/free_sign.py revoke --id 7

# 提交所有已过反悔期的挂单
python scripts/free_sign.py commit

# 自定义 DB / 规则文件
python scripts/free_sign.py --db sqlite:///my.db --rules config/rules.yaml propose --manager 1 --player 42
```

#### 批量操作

先生成模板，再填写后批量导入：

```bash
# 1. 生成 CSV 模板
python scripts/free_sign.py batch --template > signs.csv

# 2. 编辑 signs.csv（格式见下方）

# 3. 导入
python scripts/free_sign.py batch signs.csv
```

**CSV 格式：** `manager_id,player_id[,at]`
- `at` 列可省略，省略时使用执行时刻的 UTC 时间
- `#` 开头的行为注释，空行忽略

```csv
# manager_id,player_id[,at]
1,42
2,17,2026-06-04T10:00:00Z
3,99
```

批量执行输出示例：

```
Line   Mgr    Plr  Result
--------------------------------------------------
   1     1     42  [ok] id=1
   2     2     17  [ok] id=2
   3     3     99  [denied] no transfer window open at this time
--------------------------------------------------
Total: 3  ok=2  denied=1
```

有任意一行被拒绝时，脚本以非零退出码退出；已成功的行仍会写入 DB（逐行提交）。

#### Python shell / 程序化调用

```python
from scripts.free_sign import build_service
from datetime import datetime, timezone

svc = build_service()   # 从 config/rules.example.yaml 读取 DB URL

result = svc.try_propose(manager_id=1, player_id=42,
                         posted_at=datetime.now(tz=timezone.utc))
if result.success:
    print(f"待生效，free_sign_id={result.free_sign_id}")
else:
    print(f"拒绝：{result.error}")

committed = svc.commit_due(datetime.now(tz=timezone.utc))
svc._session.commit()
```

#### Web 端集成（FastAPI 示例）

```python
from scripts.free_sign import build_service

@app.post("/free-sign/propose")
def propose(body: ProposeRequest, session: Session = Depends(get_session)):
    svc = build_service(session=session)   # 复用请求级 session，由框架管理事务
    result = svc.try_propose(body.manager_id, body.player_id,
                             posted_at=datetime.now(tz=timezone.utc))
    if not result.success:
        raise HTTPException(status_code=422, detail=result.error)
    return {"free_sign_id": result.free_sign_id}
```

#### 验证规则（rule 三.3）

| 检查 | 错误类型 |
|---|---|
| 转会窗口未开放 | `TransferError` |
| 球员已被签约（非自由球员） | `TransferError` |
| 同一冷却期内已有未撤销的自由签（rule 三.6） | `TransferError` |
| 大名单总人数已达上限 | `EligibilityError` |
| 该位置人数已达上限 | `EligibilityError` |
| 余额 < 10m | `EligibilityError` |
| `FREE_SIGN_SAME_WINDOW` / 其他资格限制 | `EligibilityError` |

`try_propose` / `try_revoke` 捕获以上所有异常，返回 `FreeSignResult(success, free_sign_id, error)`，不向上抛出。

冷却期（rule 三.6）：每个玩家在 `free_sign_period_seconds` 内只能提交一笔未撤销的自由签；已撤销的不计入冷却。

生效后（rule 三.7）：若 `transfer.same_window_block_after_free_sign: true`，`commit_due` 会写入 `FREE_SIGN_SAME_WINDOW` 资格封锁，同一窗口内其他玩家不得签约该球员。

## 参考

- [`RULES.md`](./RULES.md) — FME-2021 规则原文
- [`DESIGN.md`](./DESIGN.md) — 架构说明
- [SQLAlchemy 2.0 ORM](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- [Pydantic v2](https://docs.pydantic.dev/latest/)
- [Sealed-bid auction (Wikipedia)](https://en.wikipedia.org/wiki/Sealed-bid_auction)

## 货币单位约定

所有金额（玩家余额、bid 出价、自由签 fee、奖金、出线/晋级奖等）均以**百万欧元**为单位的整数存储。YAML/数据库里写 `600` = 6 亿欧。换言之，"10m" 在代码中表达为 `10`，不是 `10_000_000`。
