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

## 参考

- [`RULES.md`](./RULES.md) — FME-2021 规则原文
- [`DESIGN.md`](./DESIGN.md) — 架构说明
- [SQLAlchemy 2.0 ORM](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- [Pydantic v2](https://docs.pydantic.dev/latest/)
- [Sealed-bid auction (Wikipedia)](https://en.wikipedia.org/wiki/Sealed-bid_auction)

## 货币单位约定

所有金额（玩家余额、bid 出价、自由签 fee、奖金、出线/晋级奖等）均以**百万欧元**为单位的整数存储。YAML/数据库里写 `600` = 6 亿欧。换言之，"10m" 在代码中表达为 `10`，不是 `10_000_000`。
