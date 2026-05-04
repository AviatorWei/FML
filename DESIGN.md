# FMLWC 范特西足球游戏后端 — 设计文档

> 版本: v0.2 · 与 FME-2021 (Euro 2020/2021) 规则完整对齐
> 仅设计与模块骨架，方法体均为 `TODO`。
> 规则原文见 `RULES.md`，所有数字与开关都参数化在 `config/rules.example.yaml`。

---

## 0. 设计原则

1. **规则即配置** — 数值（人数、初始资金、位置帽、出场帽、自由签费、奖金公式系数等）全部进 YAML，引擎不写死任何数。
2. **策略可插拔** — 暗标 tiebreaker、级联失效顺序、抽签算法、计分/PK 算法、阵容默认填充策略都做成 ABC + 策略类，YAML 选 key。
3. **资格独立建模** — "防共谋"和"解约后失格"等资格规则跨模块生效，单独抽出 `EligibilityService`，签约前必查。
4. **事件溯源** — 所有真实进球、卡牌、点球、助攻都以 `RealMatchEvent` 入库，奖金/进球/PK 都从同一份事件流派生，便于复盘和修正。
5. **幂等事务** — 暗标开标、转会成交、比赛结算都在单事务中完成。

---

## 1. 顶层流程

```
                ┌────────────────────────────────────────┐
赛季开始 ──→    │ Phase 1: 暗标 (多轮)                    │
                │   submit → close → cascade → resolve   │
                └─────────────────┬──────────────────────┘
                                  ▼
                ┌────────────────────────────────────────┐
                │ Phase 2: 转会窗 (赛程中多次开启)         │
                │   free_sign | trade | release          │
                └─────────────────┬──────────────────────┘
                                  ▼
                ┌────────────────────────────────────────┐
                │ Phase 3: 比赛 (小组赛 → 淘汰赛)          │
                │   draw → lineup → real_events → score  │
                │   knockout: + PK + pick                │
                └────────────────────────────────────────┘
                                  ▼
                ┌────────────────────────────────────────┐
                │ Phase 4: 奖金分配 + 排名                 │
                └────────────────────────────────────────┘
```

四个 Phase 之间穿插：**伤兵特例**（任意时刻可触发，退还签约费 + 可能赠送一次自由签）。

---

## 2. 模块划分

代码分三层（顶层目录），下层不依赖上层：

```
fmlwc/
├── core/                       基础内核（无外部依赖）
│   ├── enums.py                Position / Phase / BidStatus / ...
│   ├── exceptions.py           异常树
│   └── config.py               GameRules（YAML 强类型加载）
├── persistence/                存储层（仅依赖 core）
│   ├── base.py                 DeclarativeBase
│   ├── db.py                   make_engine / session_scope
│   ├── repositories.py         Protocol + SQL 实现
│   └── models/                 ORM 按聚合分文件
│       ├── people.py           Manager / Player / RosterEntry
│       ├── auction.py          AuctionRound / Submission / Bid / AuctionResult
│       ├── transfer.py         TransferWindow / FreeSign / Trade / TradeLeg / Release
│       ├── eligibility.py      EligibilityRecord
│       ├── match.py            Gameweek / Fixture / Lineup / RealMatchEvent / MatchResult / BonusAward
│       ├── knockout.py         RosterSnapshot / Pick
│       └── injury.py           InjuryAdjustment
└── domain/                     业务层（依赖 core + persistence）
    ├── eligibility.py          签约闸门（跨域，单文件）
    ├── auction/                bounded context: 暗标
    │   ├── bids.py             单笔合法性 (规则 二.3)
    │   ├── cascade.py          位置帽 + 预算级联失效 (二.4 / 二.5)
    │   ├── tiebreaker.py       归属优先级 (二.6)
    │   └── service.py          整轮编排
    ├── transfer/               bounded context: 转会窗
    │   ├── free_sign.py        自由签 + 反悔
    │   ├── trade.py            多球员+现金交易
    │   └── release.py          解约 + 反悔
    ├── lineup/                 bounded context: 阵容
    │   ├── validator.py        位置帽/向后顶替/错位静默丢弃
    │   └── defaults.py         默认填充策略
    ├── match/                  bounded context: 比赛
    │   ├── events.py           真实事件归一化
    │   ├── scoring.py          FME 进球
    │   ├── bonuses.py          助攻/红人/蓝队/罚失点球
    │   ├── schedule.py         抽签 + 赛程 + 括号
    │   ├── group_stage.py      积分与多重 tiebreak
    │   ├── knockout.py         PK 顺序 + PK 得分
    │   └── pick.py             挑人
    ├── prize.py                出线奖 + 晋级奖（单文件）
    ├── injury.py               伤兵特例（单文件）
    └── season.py               状态机编排器（单文件）
```

**分包策略**：domain 下文件多于 1 个的领域用子包（`auction` / `transfer` / `lineup` / `match`），单文件领域不强加 `__init__.py`+1 文件的样板（`eligibility` / `prize` / `injury` / `season`）。

**ORM 拆分策略**：`persistence/models/` 按业务聚合分文件，每个文件 1～6 个表；`__init__.py` 重新导出，外部仍可 `from fmlwc.persistence.models import Manager` 一行获得任意模型。

---

## 3. 数据模型 (ORM 概览)

### 3.1 主体

| 表 | 关键字段 |
|---|---|
| `managers` | id, display_name, balance, group_letter, total_points, eliminated_at |
| `players` | id, name, jersey_no, position, real_team, market_value |
| `roster_entries` | id, manager_id, player_id, acquired_at, acquired_via, acquired_price |

### 3.2 暗标

| 表 | 关键字段 |
|---|---|
| `auction_rounds` | id, index, opens_at, closes_at, status |
| `submissions` | id, round_id, manager_id, received_at, source_file, status |
| `bids` | id, submission_id, player_id, amount, rank_in_position, status (VALID/INVALID_*/AWARDED/LOST) |
| `auction_results` | id, round_id, player_id, winner_manager_id, price |

### 3.3 转会与资格

| 表 | 关键字段 |
|---|---|
| `transfer_windows` | id, opens_at, closes_at, free_sign_period_seconds, status |
| `free_signs` | id, window_id, manager_id, player_id, fee, posted_at, revoked, effective |
| `trades` | id, window_id, initiator_id, counterparty_id, status, proposed_at |
| `trade_legs` | id, trade_id, side, player_id NULL, cash_amount NULL |
| `releases` | id, manager_id, player_id, posted_at, revoked, effective |
| `eligibility_records` | id, manager_id, player_id, restriction_type, valid_until, reason |

`restriction_type` 枚举：
- `AUCTION_OTHERS_NEXT_WINDOW` — 该球员在某轮暗标被签后，**其他**经理在紧邻的下一个转会窗内不得签约（即使已被解约）
- `FREE_SIGN_SAME_WINDOW` — 同一转会窗内已被自由签后，其他经理同窗口不得签
- `RELEASED_LIFETIME` — 解约者本人本赛季不得再签该球员
- `KNOCKOUT_PICK_BLACKLIST` — 挑人冲突等扩展点

### 3.4 比赛

| 表 | 关键字段 |
|---|---|
| `gameweeks` | id, index, phase (GROUP/QF/SF/F), lineup_deadline, status |
| `fixtures` | id, gameweek_id, home_manager_id, away_manager_id, group_letter NULL, bracket_slot NULL |
| `lineups` | id, fixture_id, manager_id, starters JSON [{player_id, slot_position}], pk_order JSON NULL, posted_at |
| `real_match_events` | id, gameweek_id, real_match_id, real_player_id, event_type (GOAL/OWN_GOAL/SAVED_PEN/MISSED_PEN/ASSIST/YC/2YC/RC), value, minute |
| `match_results` | id, fixture_id, home_goals, away_goals, outcome, pk_winner_id NULL |
| `bonus_awards` | id, fixture_id, manager_id, bonus_type, amount |

### 3.5 挑人 / 伤兵

| 表 | 关键字段 |
|---|---|
| `roster_snapshots` | id, manager_id, taken_at, reason (KO_MATCH_START), entries JSON |
| `picks` | id, knockout_fixture_id, picker_manager_id, picked_player_id, picked_at |
| `injury_adjustments` | id, real_player_id, removed_at, refund_amount, free_sign_grant |

---

## 4. 核心算法

### 4.1 暗标级联失效（最重要）

输入：一份 `Submission` 内全部 `RawBid` (player_id, amount, rank)。
按规则二.3 ~ 二.5 顺序计算 valid set。

```
Step 0  逐条单笔合法性 (规则二.3)
        amount ∈ ℕ⁺, rank ∈ ℕ⁺, amount ≥ 10m,
        amount ≤ manager.balance_at_close,
        manager 当前对该 player 有签约资格 (EligibilityService),
        否则 status = INVALID_PER_BID

Step 1  位置帽级联 (规则二.4)
        for pos in [F, M, D, G]:           # 注意：位置处理顺序 F→M→D→G
          while valid bids 中 pos 数 + 现有大名单 pos 数 > 位置上限:
            在该 pos 的 valid bids 中挑最高 amount;
            若并列：rank 小者优先视为无效 (规则二.5 同价裁决)；
            标 INVALID_POS_CAP

Step 2  预算级联 (规则二.5)
        while sum(valid.amount) > balance:
            找 valid 中最高 amount；
            并列时按 [F>M>D>G] 然后 rank 小者优先；
            标 INVALID_BUDGET
```

### 4.2 球员归属（规则二.6）

```
对每个 player p, 取所有 status=VALID 且 player_id=p 的 bid，按
  (-amount, rank, submission.received_at, committee_draw_seed)
排序，取首位为 winner。
扣款 = bid.amount，写 auction_results。
```

> 注意：规则原文把"暗标截止时玩家剩余资金"作为单笔合法性的上限，且级联完成后总和 ≤ 余额；因此真实开标时**赢家一定有钱付**，无需再做余额二次校验。

### 4.3 阵容校验（规则四）

- 总人数 ∈ [8, 10]，必须含 1 GK
- 每位置上限：G ≤ 1, D ≤ 3, M ≤ 4, F ≤ 2（出场帽）
- 球员 `slot_position` 可与其本职位置不同；合法性：`actual ≥ slot` 在 `[F, M, D, G]` 顺序上（数值大可代替数值小，**G 与 F 不可越位置代替**）
  - 具体：D 可以打 M/F；M 可以打 F；其他不可。
- 错位球员**不进入首发**但不罚（规则四.9）。
- 空阵容默认沿用上轮，首轮默认按真实身价 top-N 自动填充。

### 4.4 有效进球（规则零.4 + 五.2）

```
team_goals(manager, fixture) =
    Σ events where event.player ∈ lineup.starters
    且 event.gameweek = fixture.gameweek
    且 event.type ∈ {GOAL, OWN_GOAL, SAVED_PENALTY_BY_GK}
```

注：点球大战事件不计；只算常规时间 + 加时（导入器在归一化时已过滤）。

### 4.5 单场奖金（规则七.2）

```
助攻奖    +5m × (assists by starters)
红人红卡奖 +5m × (red cards by starters, regardless of own/opponent)
蓝队奖    if (conceded > 5 and net < -2): +(2*conceded - scored) m
罚失点球奖 +3m × (missed penalties by starters in regular/ET)
```

每个奖金以 `BonusRule` 实现，配置里关掉某项即不发。

### 4.6 PK 系统（规则六.4）

```
pk_score(player) = 2*goals + 1*assists - 0.3*YC - 0.7*2YC - 1*RC
                  + 0.5 if 该球员真实球队当轮欧洲杯晋级

resolve_pk(home_lineup.pk_order, away_lineup.pk_order):
    sum_home_top5 vs sum_away_top5  -> 决出胜者；并列继续
    第 6 位单独比；并列继续
    ...
    若一方阵容耗尽，另一方直接胜
```

PK 顺序缺省：F 全队按首发顺序 → M → D → G。

### 4.7 小组赛排名（规则五.4）

依次比较：积分 → 进球数 → 失球数 → 相互交手 → 实际入欧洲杯淘汰赛球员数 → 抽签。"相互交手"在多队相同时只用相关比赛子集计算（标准 mini-table 算法）。

### 4.8 出线奖与晋级奖（规则七.3 ~ 7.5）

```
qualify_prize:
    eliminated_pool = Σ balance(eliminated_at_group_stage)
    weight(m) = group_points(m) + 0.5 * group_goals(m)
    share(m)  = round( eliminated_pool * weight(m) / Σ weights ) + 80m

advance_prize(round_r):
    eliminated_pool = Σ balance(eliminated_in_round_r)
    weight(m) = net_goals_in_round_r(m) + 1
    share(m)  = round( eliminated_pool * weight(m) / Σ weights ) + 80m
```

四舍五入按 1m 取整（`round_half_up`）。

### 4.9 挑人（规则六.6）

- 触发：每场淘汰赛胜方
- 对手 roster 取**该场比赛开始前**的快照（`roster_snapshots`）
- 资格校验同 `EligibilityService`（解约失格、防共谋等仍生效）
- 不扣资金，立即写 roster_entries（acquired_via = `KO_PICK`）

### 4.10 伤兵特例（规则九）

事件源：UEFA / 国家队足协官方推。
触发：`InjuryAdjustmentService.process(real_player_id, removed_at)`：

```
if 球员是有主球员:
    refund 最近一次签约/交易支付的资金给当前主队
    if removed_at 在自由签之后:
        给当前主队"额外一次自由签"权 (next free_sign_window)
        若该球员是 GK 且当前主队无其他 GK 且 余额 = 0:
            额外赠送 10m
```

---

## 5. 资格管理 EligibilityService

唯一的入口检查 `can_sign(manager, player, via, at) -> (allowed: bool, reason: str)`。
内部按下列规则汇总：

```
1. RELEASED_LIFETIME       — 解约者本赛季永久失格
2. AUCTION_OTHERS_NEXT_WINDOW — 暗标签出后，其他经理在下一个转会窗失格
3. FREE_SIGN_SAME_WINDOW    — 自由签后，同窗其他经理失格
4. ROSTER_FULL              — 总名单已满 20
5. POSITION_CAP             — 加入后超位置帽
6. BALANCE                  — 现金不足以支付 fee
```

每条独立成 `EligibilityRule`，YAML 可关闭/调整有效期。

---

## 6. 动态参数 Schema

`config/rules.example.yaml` 是单一事实源；`fmlwc/config.py` 用 `pydantic`(或 `dataclass + cattrs`)做强校验。完整字段见该文件，节选：

```yaml
scope: { name: "Euro 2024 League", short: "FME-24" }
managers: { count: 16, initial_budget: 600_000_000, groups: 4 }
roster:
  total_cap: 20
  position_caps: { G: 2, D: 6, M: 8, F: 4 }
auction:
  rounds: [{ index: 1, opens_at: ..., closes_at: ... }]
  min_bid: 10_000_000
  tiebreaker: "amount_rank_time_draw"
  cascade_position_order: [F, M, D, G]
lineup:
  starters_min: 8
  starters_max: 10
  appearance_caps: { G: 1, D: 3, M: 4, F: 2 }
  must_have: [G]
  backward_substitution: { D: [M, F], M: [F] }
  default_strategy: "previous_round_then_top_value"
transfer:
  free_sign_fee: 10_000_000
  free_sign_cooldown_seconds: 86400        # 自然时间，可配 12/1/0.5h
  revoke_window_seconds: 900
  trades_allow_cash: true
match:
  group_stage: { rounds: 3, points: { W: 3, D: 1, L: 0 } }
  knockout:
    bracket: "euro2024"                     # 预置括号映射
    pk_score: { goal: 2, assist: 1, YC: -0.3, 2YC: -0.7, RC: -1, advance_bonus: 0.5 }
    pk_default_order: [F, M, D, G]
bonuses:
  assist: 5_000_000
  red_card: 5_000_000
  blue_team:
    threshold_conceded: 5
    threshold_net: -2
    formula: "2*conceded - scored"
  missed_penalty: 3_000_000
prizes:
  qualify: { extra: 80_000_000, weight: "points + 0.5*goals" }
  advance: { extra: 80_000_000, weight: "net_goals + 1" }
  rounding: "half_up_million"
injury:
  enable_free_sign_grant: true
  gk_zero_balance_grant: 10_000_000
```

---

## 7. 扩展点

新规则只要新增策略类 + 在 YAML 改 key：

- `TiebreakerStrategy.compare(bid_a, bid_b) -> int`
- `CascadeInvalidator.run(submission) -> List[Bid]`
- `PairingStrategy.draw(managers, gameweek) -> List[Fixture]`
- `LineupDefaultStrategy.fill(manager, gameweek) -> Lineup`
- `BonusRule.compute(fixture, lineup, events) -> Award`
- `PrizeWeightFormula.weight(manager_stats) -> float`

---

## 8. CLI 演示

`scripts/demo_cycle.py` 用 in-memory SQLite 跑通一个迷你赛季：

1. 加载 YAML，初始化 16 manager
2. 录入一份精简球员名单
3. 跑 1 轮暗标，3 个 manager 提交标书（手工构造），打印开标结果与各方余额
4. 开第 1 个转会窗：1 次 free_sign + 1 次 trade + 1 次 release
5. 抽签生成 group A 的 3 轮赛程
6. 录入第 1 轮真实事件，提交两个 lineup，结算并打印积分榜

骨架阶段每步只调对应 service 方法，方法体留 `TODO`。

---

## 9. 后续 TODO

- 服务方法体填充
- Alembic 迁移
- 真实数据导入器（API/CSV 适配 OPTA、UEFA、Whoscored）
- 单测：暗标级联、阵容校验、PK 解析、奖金公式（建议优先）
- 直播帖 24 小时锁定 / 异议机制（可作为状态字段 `MatchResult.locked_at`）

---

## 10. 参考

- 用户提供 FME-2021 规则原文：见仓库 `RULES.md`
- 通用 fantasy 计分参考：[FPL Rules](https://fantasy.premierleague.com/help/rules)
- 暗标拍卖与 tiebreaker 设计：[Sealed-bid auction (Wikipedia)](https://en.wikipedia.org/wiki/Sealed-bid_auction)
- SQLAlchemy 仓储模式：[SQLAlchemy ORM Quickstart](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- Pydantic 配置校验：[pydantic v2 docs](https://docs.pydantic.dev/latest/)
