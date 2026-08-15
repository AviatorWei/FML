# Rules Compliance Review — three league forms

Cross-check of the engine + webapp against **RULES.md** (FME-2021, the
customized cup) and **fml-fmc-rules.md** (FML league + FMC cup 2024-25).

Legend: ✅ implemented · ⚙️ covered by configuration · 🔶 partial /
operational convention · ❌ not implemented (listed under Gaps).

Configs: `config/rules.example.yaml` (mode C), `config/rules.fml-fmc.example.yaml`
(modes A+B together).

---

## Mode A — League only (FML, fml-fmc-rules.md 第一部分)

| Rule | Requirement | Status |
|---|---|---|
| 第九条 | FML goal = goal / own goal / GK-saved pen (regular time) | ✅ `ValidGoalCalculator` + `valid_goal` config |
| 第八条 | Valid-match windows (Fri–Mon / Tue–Thu, no make-up games) | 🔶 operational — the admin only enters events from valid matches; engine has no fixture-calendar check |
| 第十二条 | 600m start; **5m per conceded goal** bonus | ✅ budget config; ✅ `ConcededGoalBonus` (credited at finalize, not at next window opening — same totals, noted deviation) |
| 第十七条 | Five positions incl. **W (边锋)** | ✅ `Position.W` added engine-wide |
| 第二十二–二十五条 | Sealed bids: ≥10m, ≤balance, rank rules, 22-cap cascade, F>W>M>D>G tie order, amount>rank>time>draw | ✅ `BidValidator` / `CascadeInvalidator` / `AmountRankTimeDraw`; tie order via `cascade.position_priority` config |
| 第二十六条 | Auction next-window sign block | ✅ `AUCTION_OTHERS_NEXT_WINDOW` |
| 第二十九–三十三条 | Free sign: 10m, one per period, 15-min revoke, same-window block | ✅ `FreeSignService` |
| 第三十五/三十六条 | Lineup 8–11; exactly 1 G; ≤2 F; ≤4 F+W; ≤7 F+W+M | ✅ new `lineup.group_caps` + validator group-cap check |
| 第四十条 | Default lineup: previous round → top value | ✅ `defaults.py`, applied at finalize |
| 第四十一条 | Misspelled/misplaced player silently dropped | ✅ validator drop semantics |
| 第四十二/四十三条 | **Reserve team** (roster − starters), parallel double round-robin | ✅ reserve goals computed at finalize (`MatchResult.home/away_reserve_goals`) + `/api/standings/reserve` |
| 第四十六条 | Table: points → GF → GA(多者在前) → h2h… → draw | 🔶 league endpoint sorts points/GD/GF; full FML chain (GA-more-first, h2h) available in `GroupStandings` engine, not yet used by the public endpoint |
| 第四十九条 | Trade forms; players-for-cash ≥10m per player | ✅ `min_cash_per_player` check in `TradeService` |
| 第五十/五十一条 | ≤3 owners per season; ≤1 trade/window; trade re-sign block | ✅ `max_owners_per_season`, `max_per_window_per_player`; ✅ giver's lifetime re-sign block recorded on trade acceptance |
| 第五十六–六十条 | Release anytime, 15-min revoke, no refund, lifetime block | ✅ `ReleaseService` (note: player held on roster during revoke window, so the "already signed by someone else" revoke-invalidation case cannot arise — conservative equivalent) |
| 第六十一条 | Auto-release when player leaves the four leagues | 🔶 admin-triggered via dismiss/release; no feed-driven automation |

## Mode B — League + Cup (FML+FMC, 第十二章 关系)

| Rule | Requirement | Status |
|---|---|---|
| FMC 第十条/十一条 | Cup list = owned CL players; cup-exclusive players from non-big-4 CL teams | ✅ `cup.extra_teams` / `league_teams_in_cup`; cup list derived pre-fork (`/api/cup/roster`) |
| 第七十七条 (group stage) | Shared roster: operations on dual players hit both games; dual players start in both | ✅ single-roster linkage; cup lineups draw from owned cup-eligible players |
| **第七十七条 (knockout)** | **FML 与 FMC 独立** — rosters fork, operations become per-game | ✅ `CupState` + `cup_roster_entries` fork; auto-fires when first CUP knockout gameweek goes LIVE (also `POST /api/cup/separate`); post-fork CUP lineups validate against the forked cup roster; release supports `competition=CUP` |
| 第七十八条 | 300m cup wallet; group stage: cup funds only for cup-exclusive players; unrestricted after | ✅ `Manager.cup_balance` + `initial_cup_budget` + `check_cup_spend` routing in roster-add; `CupWalletManagerRepo` adapter for running FMC auctions against the cup wallet |
| FMC 第四十四条 | Swiss-style 8 rounds, 4 pots by auction spend | ⚙️ fixtures are admin-scheduled (any pairing plan); pot seeding is manual |
| 第四十七条(6) | Tiebreak: count of players whose real team advanced | ⚙️ `real_qualifier_count` in tiebreak config (engine `GroupStandings` chain) |
| 第五十三条 | Aggregate → away goals → PK → draw | ⚙️ `knockout.advance_priority` |
| 第五十四/五十五条 | PK order + PK score (2/1/−0.3/−0.7/−1/+0.5) | ✅ lineup `pk_order` + `PkResolver` + config |
| 第五十七条 | 挑人 from loser's pre-match list | ✅ `PickService` snapshot + pick |
| 第六十七条 | Five per-match bonuses incl. 主场失球奖 | ✅ all five (`HomeConcededBonus` added); 🔶 bonus set is global per deployment, not per-competition — run FML and FMC with different bonus configs if strict separation is needed |
| 第六十八/六十九条 | Qualify/advance prize pools + 80m | ✅ `PrizeDistributor` + config |
| Standings split | League table counts LEAGUE gameweeks; cup bracket counts CUP | ✅ competition filter in standings |

## Mode C — Customized cup (FME-2021, RULES.md)

The engine was built from RULES.md and remains the default
(`rules.example.yaml`, `cup.enabled: false` — nothing changes):
auction cascade 二.4/二.5 ✅ · tiebreak 二.6 ✅ · lineup 四 (caps, backward
substitution D→M/F, M→F, silent drop) ✅ · FME goal counting 零.4 ✅ ·
group tiebreak 五.4 ⚙️ · PK 六.4 ✅ · picks 六.6 ✅ · prizes 七.3/七.4 ✅ ·
release/dismiss/injury 八/九 ✅.

---

## Remaining gaps (all three modes)

1. **Calendar validity (FML 第八条)** — no model of real-match calendars;
   event validity is the operator's responsibility at entry time.
2. **Public league table tiebreak chain** — swap the webapp's simple sort
   for the engine `GroupStandings` chain to get h2h and GA-more-first.
3. **Per-competition bonus sets** — one `bonuses:` config per deployment.
4. **Feed-driven auto-release (第六十一/七十六条)** and BBS-specific
   process rules (post formats, 教练组, voting) — out of engine scope.
5. **Post-fork cup trades** — league trades use `TradeService`; cup-side
   trades after separation must currently be done via cup release + admin
   roster add.

## How to run each mode

| Mode | Config | Notes |
|---|---|---|
| League only | `rules.fml-fmc.example.yaml` with `cup.enabled: false` | all gameweeks LEAGUE; reserve table on `/api/standings/reserve` |
| League + cup | `rules.fml-fmc.example.yaml` as shipped | CUP gameweeks for FMC rounds; fork happens at first CUP knockout LIVE |
| Customized cup | `rules.example.yaml` | FME-2021 behaviour, unchanged |
