# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FMLWC is a rule-configurable fantasy football engine aligned with FME-2021 (Euro 2020/2021) rules. It manages a multi-phase game: sealed-bid auctions, transfer windows, lineup validation, group stage, and knockout tournaments.

**Status:** v0.1.0 — All domain service method bodies are `NotImplementedError` stubs. Architecture, ORM, config loader, enums, and test infrastructure are complete. The main task is implementing the service methods.

## Commands

```bash
make test          # Run all tests
make test-v        # Verbose test output
make test-cov      # With coverage report
make lint          # ruff check
make typecheck     # mypy validation
make env-create    # Create conda environment
make env-update    # Update conda environment
```

Run a single test file:
```bash
python -m pytest tests/test_auction_cascade.py -v
```

**Python 3.11+ required.** Core dependencies: SQLAlchemy 2.0, Pydantic v2, PyYAML 6.0.

## Architecture (3 Layers)

```
fmlwc/core/          # Layer 1: No external deps — enums, exceptions, config types, YAML loader
fmlwc/persistence/   # Layer 2: ORM models (~40 tables across 8 files) + repository protocols + SQL impls
fmlwc/domain/        # Layer 3: Business logic services — depends on core + persistence
```

**Single fact source:** `config/rules.example.yaml` — all game parameters (budgets, caps, fees, deadlines). Never hardcode values; always read from `GameRules`. Supports `m` shorthand (e.g., `600m` = 600,000,000).

## Domain Logic Map

| Service/Module | Rule | Status |
|---|---|---|
| `domain/auction/cascade.py` — `CascadeInvalidator` | 二.4, 二.5 | **Top priority** |
| `domain/auction/tiebreaker.py` — `AmountRankTimeDraw` | 二.6 | **Top priority** |
| `domain/lineup/validator.py` — `LineupValidator` | 四 | **Top priority** |
| `domain/match/knockout.py` — `PkResolver` | 六.4 | **Top priority** |
| `domain/prize.py` — `PrizeDistributor` | 七.3, 七.4 | **Top priority** |
| `domain/eligibility.py` — `EligibilityService` | cross-cutting | — |
| `domain/auction/bids.py` — `BidValidator` | 二.3 | — |

## Key Algorithms

### Auction Cascade (rules 二.4–二.5)
1. Per-bid validation: amount ≥ 10m, amount ≤ balance, rank positive, player eligible
2. **Position-cap loop** (F→M→D→G): drop highest-amount VALID bid until cap holds; ties broken by rank
3. **Budget loop**: while sum(valid amounts) > balance, drop highest bid; ties by position priority (F>M>D>G), then rank

### Lineup Validation (rule 四)
- Appearance caps (slot position, not actual): G ≤ 1, D ≤ 3, M ≤ 4, F ≤ 2
- **Backward-substitution:** D can play M/F slot; M can play F slot; others misplaced → silent drop
- Must include ≥1 GK; size 8–10; all players must be on roster

### FME Goal Counting (rule 零.4)
Count only starters in regular+extra time: Goal=+1, Own Goal=+1, Saved Penalty (by GK)=+1. Penalty shootout events are excluded.

### Group Stage Tiebreaker Chain (rule 五.4)
Points → Goals For → Goals Against (more = better, per rules) → H2H mini-table points → real qualifiers in roster → SHA256 draw seed

### PK Score (rule 六.4)
`2×goals + 1×assists - 0.3×YC - 0.7×2YC - 1×RC + 0.5 (if real team advanced)`
Resolution: compare top-5 sums → top-6 individual → ... → if one team has no players, other wins.

### Prize Distribution (rules 七.3–七.4)
Qualify prize: weight = points + 0.5×goals_for. Advance prize: weight = net_goals + 1. All monetary rounding is **half-up to nearest million**.

### Eligibility Restrictions (4 types)
- `AUCTION_OTHERS_NEXT_WINDOW` — non-winners blocked until next transfer window
- `FREE_SIGN_SAME_WINDOW` — others blocked through window end
- `RELEASED_LIFETIME` — releaser permanently ineligible this season
- `KNOCKOUT_PICK_BLACKLIST` — pick conflicts (future)

## Testing Approach

Unit tests use **in-memory fake repositories** (`tests/fakes.py`) — no SQLAlchemy dependency in domain tests. `tests/sample_rules.py` provides a default `GameRules` config. Do not use the real SQLAlchemy repos in unit tests.

`RULES.md` is the authoritative rule text. `DESIGN.md` has detailed algorithm explanations. When in doubt about business logic, check `RULES.md` first, then `DESIGN.md`.
