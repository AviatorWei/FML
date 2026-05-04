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

Status: algorithmic core complete (12 modules), DB-orchestration layer is TODO.
**100/100 tests pass** as of last commit.

---

## 2. Layered structure (3 layers, dependency direction is one-way)

```
fmlwc/core/         — enums, exceptions, config (no external deps; everyone may import)
fmlwc/persistence/  — SQLAlchemy: base, db, models/{7 files}, repositories
fmlwc/domain/       — business services
    eligibility.py  — single chokepoint for "may X sign Y at T?" (cross-cutting)
    auction/        — bids, cascade, tiebreaker, service     (sub-package: 4 files)
    transfer/       — free_sign, trade, release              (sub-package: 3 files)
    lineup/         — validator, defaults                    (sub-package: 2 files)
    match/          — events, scoring, bonuses, schedule, group_stage, knockout, pick
    prize.py        — qualifier + advancement prizes
    injury.py       — UEFA squad-removal exception
    season.py       — top-level state machine (TODO)
```

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
  `valid_goal`, NOT `valid_goals`. (Was `fme_goal/fme_goals` historically — renamed.)
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
- `RELEASED_LIFETIME` — the record's `manager_id` is the releaser. THEY are blocked.

If you add a new restriction type, you must update both `check()`'s dispatch and
`record_*` writer helpers.

---

## 7. How to run tests

Two ways:

```bash
# (1) sandbox-friendly runner (no pytest install required, uses a minimal shim)
python tests/_runner.py

# (2) standard pytest (after `pip install pytest pyyaml sqlalchemy`)
pytest tests/
```

Tests use **in-memory fakes** from `tests/fakes.py` (FakeManagerRepo, FakePlayerRepo,
FakeEligibilityRepo, FakeBidRepo, FakeTransferRepo). They implement the same Protocol
shapes as `persistence.repositories`. **Don't write tests against SqlAlchemy in unit
tests** — keep that for an integration test suite (TODO).

`tests/sample_rules.py::default_rules()` is the canonical test config builder. Tests
that need to tweak one field do `raw_dict()` → mutate dict → `GameRules.from_dict(d)`.

### Test priorities (most valuable to extend)
1. `auction.cascade` — position-cap × budget × total-roster cap interactions
2. `auction.bids` — conditional-release edge cases
3. `lineup.validator` — backward sub combinations × misplaced silent-drop
4. `match.knockout.PkResolver` — exhaustion cases
5. `prize.PrizeDistributor` — half-up rounding boundaries (0.5, 2.5)

---

## 8. Pitfalls & gotchas (please don't relearn these)

### Tooling
- **`Write` tool truncates files around ~150 lines.** When writing a file longer
  than that, use `cat > file <<'EOF'` (bash heredoc) instead. Symptom: file silently
  cut mid-line, leading to `SyntaxError: unterminated string literal`.
- Sometimes `Write` introduces null bytes (`b'\x00'`) into freshly-created files,
  which makes Python `import` fail with `ValueError: source code string cannot contain null bytes`.
  If you see this, rewrite the file with bash heredoc.

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

### Config
- The `m` shorthand in `_as_int` is a no-op identity since the unit migration —
  `"600m"` → 600, same as `600`. Keep it for backward compat in YAML.
- `GameRules` is a frozen dataclass tree — never mutate; build a new dict and reload.

---

## 9. What's TODO (in priority order)

1. `fmlwc/persistence/db.py` — `make_engine`, `make_session_factory`, `session_scope`.
2. SQL implementations of repos (`SqlManagerRepo` etc.) — start with `SqlEligibilityRepo`,
   smallest and most reused.
3. `fmlwc/domain/auction/service.py::resolve()` — wires cascade + tiebreaker + balance
   adjustment + eligibility records into one DB transaction.
4. `fmlwc/domain/transfer/{free_sign,trade,release}.py` — DB state transitions with
   15-min revoke windows.
5. `fmlwc/domain/match/pick.py` — knockout-winner pick (uses `RosterSnapshot`).
6. `fmlwc/domain/lineup/defaults.py::PreviousRoundStrategy` and `TopValueStrategy`.
7. `fmlwc/domain/season.py::SeasonOrchestrator` — phase state machine.
8. Alembic migrations (replace `db.create_all`).

When implementing the DB layer, expect:
- **Single transaction per operation.** `auction.service.resolve` MUST run cascade
  + tiebreaker + balance adjustments + eligibility writes inside one `session.begin()`.
- **Snapshot before mutate.** `current_position_counts` and balances passed to the
  cascade must be the *open-of-resolution* snapshot, not updated as winners are
  awarded inside the loop.
- **Idempotency.** `submit()` must overwrite any prior submission for the same
  (round, manager) tuple per rule 二.2.

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

---

## 11. Quick orientation checklist

When you sit down to make a change, ask yourself:

- [ ] Does my change need a config knob? If yes, add to `_config_types.py` + a parser
      in `config.py` + the YAML example + `tests/sample_rules.py::_BASE`.
- [ ] Money? Add `# unit: million EUR` comment.
- [ ] New signing pathway? Add an `AcquisitionVia` enum and route through
      `EligibilityService.check`.
- [ ] New validation result? Extend `BidStatus` enum, NEVER add ad-hoc strings.
- [ ] Pure algorithm? Test with fakes; no DB.
- [ ] DB-touching? Wrap in `session_scope()` (once `db.py` is done) and document
      what's in the transaction boundary.

Run `python tests/_runner.py` before claiming done. Should print
`TOTAL: <N> passed, 0 failed`.
