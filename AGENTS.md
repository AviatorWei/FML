# AGENTS.md — Onboarding for AI agents working on FMLWC

> 这份文档是给后续 agent (或人类协作者) 的"上手便条"。
> 5 分钟读完，知道仓库长什么样、规则在哪、怎么跑测试、哪些坑别踩。

---

## 1. What is FMLWC

A rule-configurable fantasy football engine aligned with FME-2021 (Euro 2020/2021).
16 managers, sealed-bid auctions, transfer windows, group stage + knockout.

**Authoritative rule source**: [`RULES.md`](./RULES.md) — Chinese原文.
**Architecture overview**: [`DESIGN.md`](./DESIGN.md).
**Numeric source of truth**: [`config/rules.example.yaml`](./config/rules.example.yaml).
Never hardcode game numbers — always read from `GameRules`.

Status: algorithmic core + DB layer complete; orchestration layer is TODO.
**292 tests pass** as of last commit.

---

## 2. Layered structure (3 layers, dependency direction is one-way)

```
fmlwc/core/         — enums, exceptions, config (no external deps; everyone may import)
fmlwc/persistence/  — SQLAlchemy: base, db, models/{7 files}, repositories, sql_repos
fmlwc/domain/       — business services
    eligibility.py  — single chokepoint for "may X sign Y at T?" (cross-cutting)
    auction/        — bids, cascade, tiebreaker, service     (sub-package: 4 files)
    transfer/       — free_sign ✓, trade ✗, release ✗        (sub-package: 3 files)
    lineup/         — validator ✓, defaults ✗                (sub-package: 2 files)
    match/          — events, scoring, bonuses, schedule, group_stage, knockout, pick ✗, round
    prize.py        — qualifier + advancement prizes ✓
    injury.py       — UEFA squad-removal exception ✗
    season.py       — top-level state machine ✗
fmlwc/io/           — xlsx reader/writer, player list generator, free-sign interface
scripts/            — CLI helpers (init_db, free_sign, generate_player_list, run_auction1)
```

**Two repo files** — don't confuse them:
- `persistence/repositories.py` — Protocol definitions + dead-code SQL stubs (the stubs
  are superseded by sql_repos.py; they exist only as implementation guides).
- `persistence/sql_repos.py` — **the real SQLAlchemy implementations** (all complete).

Rule of thumb: **only make a sub-package when there's >1 file**.

`__init__.py` files are intentionally **lazy** — they don't re-export anything that
imports SQLAlchemy. This lets pure-algorithm modules (`cascade`, `scoring`, `prize` …)
run without SQLAlchemy installed.

---

## 3. Money unit convention (CRITICAL — easy to miss)

**Every monetary value in this codebase is an integer count of millions of euros.**

- `initial_budget: 600` means 600 m EUR (= 6 亿欧).
- `min_bid: 10` means 10 m.
- `Award.amount = 5` means 5 m.

Every monetary column in ORM and config dataclasses has a trailing
`# unit: million EUR` comment. If you add a new monetary field, add the same comment.

Don't reintroduce "raw cash units" (1 EUR per integer). The rounding helper
`fmlwc.domain.prize.round_half_up(value)` rounds to integer (= 1m granularity).

---

## 4. Naming conventions

- Singular for enum-like strings. Don't use plural forms in YAML or code as enum tags.
  `valid_goal`, NOT `valid_goals`.
- Acquisition pathways live in `enums.AcquisitionVia`: `AUCTION / FREE_SIGN / TRADE / KO_PICK / INJURY_GRANT`.
- Eligibility restrictions in `enums.EligibilityRestriction` — do NOT add new types
  without updating `EligibilityService.check`'s dispatch.

---

## 5. Auction bid mechanics (most complex part)

### Per-bid validation order (`auction/bids.py`)
1. integer types
2. `rank_in_position == 0` → invalid
3. **negative rank** → conditional-release branch (gated by `auction.conditional_release_enabled`)
4. **positive rank** → acquisition branch: amount ≥ min_bid, amount ≤ balance, eligibility records

### Conditional release (rule extension; gated by config)
- A bid with `rank_in_position < 0` marks an *existing roster player* for release.
- Rank `-1` releases first if any acquisition wins, `-2` second, etc.
- Negative ranks are **globally scoped** (not per-position) — duplicates within a
  submission are invalid.
- Conditional-release bids have no amount/balance check.
- `BidValidator.__init__` takes `(rules, managers, players, eligibility)`. The
  `managers` repo is needed to verify the player is on the bidder's active roster.

### Cascade (`auction/cascade.py`)
Three loops, all act only on **acquisition bids** (rank > 0); release bids
are bystanders that adjust the roster-cap math.

1. **Position cap loop** — for each pos in `cascade.position_priority` (default F→M→D→G),
   drop highest-priced bid in that position until cap holds.
2. **Budget loop** — drop highest-priced bid until Σ amounts ≤ balance.
3. **Total roster cap loop** — drop highest until
   `current_total + acquisitions − conditional_releases ≤ total_cap`.

Tie-break for "drop highest": (1) negate amount; (2) position priority
F>M>D>G; (3) lower rank first (rule 二.5).

### Tiebreaker (winner per player, `auction/tiebreaker.py`)
Sort key (lower wins): `(-amount, rank_in_position, received_at, draw_seed)`.
`draw_seed` is `sha256(round_id:player_id:manager_id)` for deterministic last-resort.

---

## 6. Eligibility (the gate everyone passes through)

`fmlwc.domain.eligibility.EligibilityService.check(...)` is THE single decision point
for all four signing pathways. Order:

1. roster total cap
2. position cap
3. balance (only enforced for FREE_SIGN, TRADE — auction does its own at bid time;
   KO_PICK and INJURY_GRANT are free)
4. active `EligibilityRecord` rows from the eligibility repo

Restriction semantics:
- `AUCTION_OTHERS_NEXT_WINDOW`, `FREE_SIGN_SAME_WINDOW`, `KNOCKOUT_PICK_BLACKLIST` —
  the record's `manager_id` is the *winner/holder*. Everyone ELSE is blocked.
- `RELEASED_LIFETIME`, `DISMISSED_LIFETIME` — the record's `manager_id` is the actor.
  THEY are blocked from re-signing.

If you add a new restriction type, update both `check()`'s dispatch and the
`record_*` writer helpers.

---

## 7. Free sign service (`transfer/free_sign.py`) — COMPLETE

The free-sign lifecycle mirrors the release lifecycle:

```
propose()    →  pending (revoked=False, effective=False)
revoke()     →  cancelled (within rules.transfer.revoke_window_seconds)
commit_due() →  effective=True; balance -=fee; roster updated; FREE_SIGN_SAME_WINDOW block written
```

Non-raising wrappers: `try_propose()` / `try_revoke()` return `FreeSignResult(success, free_sign_id, error)`.
`scripts/free_sign.py` exposes `build_service(session=None)` for both CLI and web use.

Cooldown (rule 三.6): any non-revoked sign within `window.free_sign_period_seconds` blocks a new one.
Revoked signs are excluded from the cooldown count.

---

## 8. How to run tests

Two ways:

```bash
# (1) sandbox-friendly runner (no pytest install required, uses a minimal shim)
python tests/_runner.py

# (2) standard pytest (after `pip install pytest pyyaml sqlalchemy`)
pytest tests/
```

Tests use **in-memory fakes** from `tests/fakes.py`. Fakes available:

| Class | Covers |
|---|---|
| `FakeManagerRepo` | roster, balance |
| `FakePlayerRepo` | `is_free_agent` via `_signed` set; call `mark_signed(id)` |
| `FakeEligibilityRepo` | eligibility records |
| `FakeBidRepo` | bids per submission |
| `FakeSubmissionRepo` | submissions |
| `FakeAuctionRoundRepo` | round status |
| `FakeAuctionResultRepo` | auction results |
| `FakeTransferRepo` | windows (has `free_sign_period_seconds` field) |
| `FakeFreeSignRepo` | free sign rows |
| `FakeDismissalRepo` | dismissal records |

**Don't write unit tests against SQLAlchemy** — keep that for `tests/test_sql_integration.py`.

`tests/sample_rules.py::default_rules()` is the canonical test config builder. Tests
that need to tweak one field do `raw_dict()` → mutate dict → `GameRules.from_dict(d)`.

### Test priorities (most valuable to extend)
1. `auction.cascade` — position-cap × budget × total-roster cap interactions
2. `auction.bids` — conditional-release edge cases
3. `lineup.validator` — backward sub combinations × misplaced silent-drop
4. `match.knockout.PkResolver` — exhaustion cases
5. `prize.PrizeDistributor` — half-up rounding boundaries (0.5, 2.5)
6. `transfer.release` — once implemented; mirror free_sign test structure

---

## 9. What's TODO (19 stubs remaining)

### Priority 1 — Transfer window completeness

#### `fmlwc/domain/transfer/release.py` (3 stubs — rule 八)
Mirror of `free_sign.py`. Same propose/revoke/commit_due lifecycle.
- `propose(manager_id, player_id, posted_at)` → release_id
  - player must be on manager's active roster
  - insert `Release` row (revoked=False, effective=False)
- `revoke(release_id, at)` → enforce `release.revoke_window_seconds`
- `commit_due(at)` → mark effective; refund `release.refund` (0m by default); if
  `release.releaser_lifetime_block`, call `eligibility.record_release_block()`

No `FreeSignRepo`-style separate repo needed — use a `ReleaseRepo` Protocol
(pattern: same 6 methods as `FreeSignRepo`; `Release` ORM model already exists).

#### `fmlwc/domain/transfer/trade.py` (4 stubs — no rule number; game-convention)
Two-sided swap with optional cash component (controlled by `transfer.trades_allow_cash`).

- `propose(initiator_id, legs, proposed_at)` → trade_id
  - validate each leg: player on proposer's roster, no cross-eligibility blocks
  - insert `Trade` (status=PROPOSED) + `TradeLeg` rows
- `accept(trade_id, at)` → one transaction: re-validate both sides at acceptance time;
  swap `RosterEntry` rows; adjust balances for cash legs; status→ACCEPTED
- `reject(trade_id, at)` → status→REJECTED (no state changes)
- `expire_window_close(window_id, at)` → mark all PROPOSED trades for this window as EXPIRED

Note: `transfer.trades_require_counterparty_accept` gates whether `accept()` is needed
or if `propose()` is auto-accepted.

---

### Priority 2 — Lineup defaults

#### `fmlwc/domain/lineup/defaults.py` (2 stubs — rule 四.8)
Auto-fill lineups when a manager hasn't submitted before deadline.

- `PreviousRoundStrategy.fill(manager_id, gameweek_id)` → `list[SlotAssignment]`
  - query `lineups` for the previous gameweek's fixture for this manager
  - return the same starters if all players still on active roster; drop released ones
- `TopValueStrategy.fill(manager_id, gameweek_id)` → `list[SlotAssignment]`
  - pick highest `market_value` players from roster, respecting `lineup.appearance_caps`
  - resolve native-position slots only (no backward subs in auto-fill)

Both strategies must return a list that passes `LineupValidator` — validate before returning.

---

### Priority 3 — Knockout phase

#### `fmlwc/domain/match/pick.py` (3 stubs — rule 六.6)
After a knockout match, the winner may pick one player from the loser's pre-match roster.

- `take_snapshot(fixture_id, manager_id, at)` → snapshot_id
  - copy current `RosterEntry` rows → `RosterSnapshot` ORM rows keyed by fixture_id
  - must be called **before** the fixture goes LIVE (season orchestrator responsibility)
- `pick(fixture_id, winner_manager_id, player_id, at)` → None
  - verify: fixture is FINALIZED; winner_manager_id is correct winner; player on loser snapshot
  - `eligibility.assert_allowed(via=KO_PICK, fee=0)` for cross-checks
  - transfer player: `release_from_roster(loser)` → `add_to_roster(winner, via=KO_PICK, price=0)`
  - record `KNOCKOUT_PICK_BLACKLIST` eligibility for conflicts
  - enforce `pick_deadline_seconds` (raise `TransferError` if too late)
- `expire_unpicked(fixture_id, at)` → None
  - called by season orchestrator after deadline; no-op if pick already made

---

### Priority 4 — Season orchestrator

#### `fmlwc/domain/season.py` (6 stubs — phase state machine)

Wires all services into a sequenced lifecycle. Each transition must be idempotent
(re-running is safe) and wrapped in a single DB transaction.

- `begin_auction()` — SETUP → AUCTION: validate managers and player list exist;
  open round 1 via `AuctionService.open_round()`
- `begin_transfer(at)` — AUCTION → TRANSFER: close final auction round; open
  `TransferWindow` row for the configured window spec
- `begin_group_stage(at)` — TRANSFER → GROUP_STAGE: close transfer window; call
  `ScheduleService.assign_groups()` + `generate_round_robin()` to create `Gameweek`
  and `Fixture` rows; set all managers' `group_letter`
- `advance_to_knockout(at)` — GROUP_STAGE → KNOCKOUT_QF: collect final group standings
  (via `GroupStandings`); seed bracket; create knockout `Gameweek` + `Fixture` rows;
  write any eligibility seeds (e.g. `KNOCKOUT_PICK_BLACKLIST` from pick conflicts)
- `settle_gameweek(gameweek_id, at)` — call default lineups for non-submitters;
  call `RoundService.finalize_gameweek()`; distribute prizes if applicable;
  advance phase if last gameweek in current phase
- `finalise()` — DONE: emit final rankings JSON; run `PrizeDistributor` for any
  remaining prize pools

---

### Priority 5 — Injury exception

#### `fmlwc/domain/injury.py` (1 stub — rule 九)
Handles UEFA squad removals mid-tournament.

- `process(player_id, removed_at)` → None
  - find current owner (if any) via `managers.list_roster` scan or a dedicated query
  - call `managers.release_from_roster(owner_id, player_id, removed_at)`
  - if `injury.refund_last_signing_fee`: refund acquisition price to owner's balance
  - if past the last transfer window AND `injury.grant_extra_free_sign_after_window`:
    create a one-off `TransferWindow` grant for the affected manager (custom logic TBD)
  - GK + zero-balance special case: if `injury.gk_zero_balance_grant > 0` and the
    released player was a GK and the manager's balance == 0, grant emergency funds

---

### Not yet planned (lower priority)

| Item | Notes |
|---|---|
| Alembic migrations | Replace `db.create_all` for production use |
| Integration test suite | SQL transaction tests; currently unit-test only |
| `repositories.py` dead stubs | The `SqlXxx` classes in repositories.py are superseded by sql_repos.py; safe to delete or leave as documentation |

---

## 10. House style / conventions

- Type hints everywhere, even on internal helpers.
- Frozen dataclasses for immutable value objects (`RawBid`, `ValidationOutcome`,
  `EligibilityVerdict`, `PrizePayout`, `Award`, `FixtureScore`, `PkOutcome`, …).
- Service `__init__` takes `rules` first, then concrete repos / sub-services.
- Domain services NEVER import `Session` directly — only Protocols from
  `persistence.repositories`.
- Per-rule comments: prefer `# rule 二.5` over re-explaining the rule. Keep
  `RULES.md` as the source.
- `try_*` wrappers (non-raising, return a `Result` dataclass) belong on services that
  have a public CLI/web interface. See `FreeSignService.try_propose` as the pattern.
- For every script required, or every new set of functionality, add them to the README file.

---

## 11. Pitfalls & gotchas (please don't relearn these)

### Code
- Don't eagerly re-export domain services from `__init__.py` — most pull SQLAlchemy
  transitively via `repositories`. Keep `__init__.py` files docstring-only.
- ORM imports inside `repositories.py` are guarded by `if TYPE_CHECKING:` so the
  Protocols can be imported without SQLAlchemy. Don't move the imports to module top.
- `Position.can_play_as()` only allows backward sub: D→M/F, M→F. G and F can never
  cross-substitute (rule 四.4).
- Group stage rule 五.4 says "失球数多者排名靠前" — i.e. MORE conceded is better.
  Don't "fix" this; it's intentional and the tiebreak key is `goals_against_more_first`.
- Penalty shootouts are excluded from goal counting AND PK scoring
  (`is_shootout=True` → skip).
- `FakePlayerRepo.is_free_agent` returns `True` by default (all players free agents).
  Call `plr_repo.mark_signed(player_id)` in tests that need a non-free-agent scenario.

### Config
- The `m` shorthand in `_as_int` is a no-op identity since the unit migration —
  `"600m"` → 600, same as `600`. Keep it for backward compat in YAML.
- `GameRules` is a frozen dataclass tree — never mutate; build a new dict and reload.

---

## 12. Quick orientation checklist

When you sit down to make a change, ask yourself:

- [ ] Does my change need a config knob? If yes, add to `_config_types.py` + a parser
      in `config.py` + the YAML example + `tests/sample_rules.py::_BASE`.
- [ ] Money? Add `# unit: million EUR` comment.
- [ ] New signing pathway? Add an `AcquisitionVia` enum and route through
      `EligibilityService.check`.
- [ ] New validation result? Extend `BidStatus` enum, NEVER add ad-hoc strings.
- [ ] New service with CLI/web exposure? Add `try_*` wrappers returning a `Result`
      dataclass; add a `build_service(session=None)` factory in `scripts/`.
- [ ] Pure algorithm? Test with fakes; no DB.
- [ ] DB-touching? Wrap in `session_scope()` and document the transaction boundary.
- [ ] New `FreeSignRepo`-style repo? Add Protocol to `repositories.py` AND real impl
      to `sql_repos.py` AND fake to `tests/fakes.py`.

Run `pytest tests/` before claiming done. All 292 tests must pass.
