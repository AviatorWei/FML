# FMLWC Frontend Design — Data Export, Roster Input, Event Input

Status: proposal (v1) · Extends the existing `webapp/` (React 18 + Vite + Tailwind frontend, FastAPI backend)

The current webapp is read-mostly: Scores, Standings, Players, Bid-file parsing (no commit), and Free Signings. This design adds the **write and export surfaces** so the whole game can be operated from the browser: exporting every artefact the league produces, entering rosters through every acquisition channel, and entering real-match events that drive scoring.

---

## 1. Roles and app structure

Two audiences, one app, gated by a role switch (an `X-Role` header + admin token; managers get a per-manager token):

| Role | Can do |
|---|---|
| **Manager** | View everything public; upload own bid sheet; submit own lineup; propose free signs, trades, releases (with revoke window) |
| **Admin (commissioner)** | Everything above for any manager, plus: commit auction rounds, edit rosters directly, enter match events, finalize gameweeks, dismissals, injury adjustments, all exports |

Navigation (additions in **bold**):

```
Live Scores · Standings · Players · Bids · Free Signings
· **Lineups** · **Admin ▾ (Rosters / Auction Desk / Events / Gameweeks / Exports)**
```

Admin pages live under `/admin/*` and are hidden unless an admin token is present (`localStorage` is unavailable in some embeds — keep the token in memory + cookie).

---

## 2. Export center (`/admin/exports`)

One page listing every exportable artefact as a card with format choice and a download button. All exports are **GET endpoints returning a file** so they also work via curl/cron.

| Artefact | Backend source | Endpoint | Formats |
|---|---|---|---|
| Player list (`ID/Name/Nation/Pos/Team/Price`) | `PlayerListExporter` + `query_player_list` | `GET /api/export/players.xlsx` | xlsx, csv |
| Bid template per manager (`FME_<year>_Bid<N>_<CODE>.xlsx`) | new writer mirroring `XlsxBidReader` sheet layout (`Order/Price/ID/Name/Team/Pos`) | `GET /api/export/bid-template?round=N&manager_code=ENG` (omit code → zip of all) | xlsx, zip |
| Auction announcement 暗标公示 | `AuctionAnnouncementFormatter` + `AuctionService.announcement_views()` | `GET /api/export/auction/{round_index}/announcement.txt` | txt |
| Auction results | `AuctionResult` rows | `GET /api/export/auction/{round_index}/results.csv` | csv, xlsx |
| Rosters (per manager or all; incl. `acquired_via/price/at`, released rows optional) | `RosterEntry` ⋈ `Player` ⋈ `Manager` | `GET /api/export/rosters.xlsx?manager_id=&include_released=` | xlsx, csv |
| Roster snapshots (knockout) | `RosterSnapshot` | `GET /api/export/roster-snapshots.json` | json |
| Lineups per gameweek | `Lineup` | `GET /api/export/lineups.csv?gameweek=N` | csv |
| Match events per gameweek | `MatchEvent` | `GET /api/export/events.csv?gameweek=N` | csv |
| Results + standings | `MatchResult`, standings calc | `GET /api/export/standings.xlsx` | xlsx, csv |
| Player/manager athletics | `PlayerAthletics`, `ManagerStats`, `ManagerPlayerAthletics` | `GET /api/export/athletics.xlsx` (3 sheets) | xlsx |
| Transfer ledger (free signs, trades+legs, releases, dismissals) | transfer tables | `GET /api/export/transfers.xlsx` (4 sheets) | xlsx |
| Prize ledger | `BonusAward`, prize tables | `GET /api/export/prizes.csv` | csv |
| Full season archive | everything above | `GET /api/export/season.zip` | zip |

UI details: each card shows row count and last-modified time (cheap `COUNT(*)`/`MAX(updated)` probe via `GET /api/export/manifest`); a "Copy curl" button; xlsx built with openpyxl (already a dependency of the exporters).

---

## 3. Roster input

Rosters change through five channels (`AcquisitionVia`): AUCTION, FREE_SIGN, TRADE, KO_PICK, INJURY_GRANT — plus removals (release, dismissal). Each gets a first-class flow instead of a generic table editor, so the engine's validation runs on every write. A raw editor exists as an escape hatch.

### 3.1 Auction Desk (`/admin/auction`) — the main roster-input flow

Wizard matching the engine pipeline:

1. **Round setup** — create/open `AuctionRound` (index, opens/closes). `POST /api/admin/auction/rounds`.
2. **Collect sheets** — multi-file drop zone for `FME_<year>_Bid<N>_<CODE>.xlsx`. Reuses the existing parse endpoint per file, shows one row per manager: code resolved → manager, bid count, total amount, per-bid min-bid check. Files can be replaced until commit. `POST /api/admin/auction/rounds/{id}/submissions` persists `Submission` + `Bid` rows.
3. **Resolve (dry run)** — `POST /api/admin/auction/rounds/{id}/resolve?dry_run=true` runs `BidValidator` → `CascadeInvalidator` → `AmountRankTimeDraw` and returns every bid with final `BidStatus` and `invalid_reason` (`INVALID_PER_BID`, `INVALID_POS_CAP`, `INVALID_BUDGET`, `INVALID_INELIGIBLE`, AWARDED, LOST). UI groups by player, highlights cascade drops, shows each manager's balance delta. This satisfies the "dry-run" item in TODOs.md.
4. **Commit** — same endpoint with `dry_run=false`: writes `AuctionResult` + `RosterEntry` (via=AUCTION), debits balances, seeds `AUCTION_OTHERS_NEXT_WINDOW` eligibility records, closes the round.
5. **Publish** — buttons for announcement txt and results csv (export center endpoints).

### 3.2 Lineup entry (`/lineups`) — manager-facing

Per gameweek, per manager (admins can act for anyone):

- Left: current roster grouped by position with per-player season stats.
- Right: pitch view with slot chips (G ≤ 1, D ≤ 3, M ≤ 4, F ≤ 2; size 8–10; ≥ 1 GK). Clicking a rostered player adds them to their native slot; a slot dropdown allows backward substitution (D→M/F, M→F) and shows why other placements will be dropped.
- **Live validation** via `POST /api/lineups/validate` (wraps `LineupValidator`, no write): renders `accepted` and `dropped` (with reasons: duplicate, not on roster, misplaced) before submission — never surprise-drop silently at the deadline even though the rule allows it.
- PK order: drag-to-reorder list of chosen starters (`pk_order`), required for knockout gameweeks.
- Countdown to `Gameweek.lineup_deadline`; submissions blocked after (server-checked). `PUT /api/lineups/{gameweek_id}/{manager_id}` upserts (unique fixture+manager).
- Banner when no lineup exists: "default lineup will be applied at settlement" (`lineup/defaults.py`).

### 3.3 Transfers (`/free-sign` extended, `/admin/roster`)

- **Free sign** — existing page; add a revoke button active for `revoke_window_seconds` after `posted_at` (`POST /api/free-sign/{id}/revoke`), and surface eligibility-block errors verbatim from `EligibilityService`.
- **Trades** — proposal form: counterparty, legs builder (each leg = player or cash, per `TradeLeg`), window check; counterparty sees pending trades and accepts/rejects; expiry per rules. `POST /api/trades`, `POST /api/trades/{id}/(accept|reject|cancel)`.
- **Release** — pick own player, confirm fee/ledger effect, revoke window like free sign; warns about `RELEASED_LIFETIME` block. `POST /api/releases`.
- **Dismissal (admin)** — immediate, reason field, warns about `DISMISSED_LIFETIME`. `POST /api/admin/dismissals`.
- **Injury adjustment (admin)** — pick injured real player → form shows current owner, refund amount (auto-suggested from acquired price), optional free-sign grant + grantee (`InjuryAdjustment`). `POST /api/admin/injuries`.
- **KO pick (admin/knockout)** — per knockout fixture: picker, picked player, blacklist check (`KNOCKOUT_PICK_BLACKLIST`). `POST /api/admin/picks`.

### 3.4 Raw roster editor (`/admin/roster`)

Table of `RosterEntry` (filter manager/status). Admin can add a row (player picker → via/price/date) or set `released_at`. Every write goes through a service-layer check (balance, one-owner-at-a-time) and is recorded with `via` so exports stay truthful. Bulk import: upload the same xlsx the export produces (round-trip format), with a diff preview before commit — `POST /api/admin/roster/import?dry_run=`.

### 3.5 Season seeding (`/admin/setup`)

Player catalogue import (csv/xlsx in `PlayerListRow` format → upsert `Player`, backed by `player_list_generator.inject_into_session`), manager creation (name, group letter, initial budget from rules), transfer-window and gameweek/fixture creation (backed by `Scheduler`).

---

## 4. Event input (`/admin/events`)

Events are keyed by **(gameweek, player)** — no fixture id needed (see `MatchEvent` docstring), which makes fast entry possible.

### 4.1 Fast-entry grid (primary)

- Header: gameweek picker (only PENDING/LIVE editable), real-match label (free text, e.g. "GER 2:1 FRA"), minute default.
- One row per event: **player search box** (same typeahead as free-sign page) → **event type** as 8 hotkeyed chips (`G` goal, `O` own goal, `A` assist, `Y` yellow, `2` second-yellow-red, `R` red, `S` saved-pen-by-GK, `M` missed pen) → minute (optional) → ET / shootout toggles.
- Enter commits the row (`POST /api/admin/events`) and focuses a fresh row — a full match is enterable in under a minute.
- Guards, warning not blocking: SAVED_PENALTY_BY_GK for a non-GK; shootout=true reminder that shootout events are excluded from FME goal counting (rule 零.4); player not in any submitted lineup this gameweek ("won't score for anyone").
- Below: live event log for the gameweek with inline edit/delete (`PUT/DELETE /api/admin/events/{id}`), grouped by real match, running per-manager valid-goal tally computed by `ValidGoalCalculator` in preview mode.

### 4.2 Bulk import

CSV upload (`gameweek,player_id,event_type,minute,is_extra_time,is_shootout`) → parsed via the `ManualImporter`/`NormalisedEvent` path → dry-run diff table → commit. Mirrors the events export format exactly, so export→edit→import round-trips.

### 4.3 Gameweek lifecycle (`/admin/gameweeks`)

Status board: each `Gameweek` card shows phase, status (PENDING → LIVE → FINALIZED), lineup deadline, fixtures, lineups submitted (n/of), events entered.

- **Set LIVE** locks lineups; **Finalize** runs `settle_gameweek`: apply default lineups → `ValidGoalCalculator` per fixture → `BonusEngine` → standings/bracket update → knockout roster snapshots. `POST /api/admin/gameweeks/{id}/finalize` returns the settlement report (per-fixture goals, `MatchResult` outcome, bonuses awarded) rendered as a confirmation screen; results become visible on the public Scores page and rows get `locked_at`.
- Knockout fixture drawn: PK panel appears when the fixture's valid-goal score ties — shows `PkResolver` breakdown (top-5 sums → top-6 …, the 2g+1a−0.3y−0.7×2y−1r+0.5adv per-player scores) and writes `pk_winner_id`; the "+0.5 real team advanced" inputs are checkboxes per real team for that round.

---

## 5. API summary (new endpoints)

```
# exports (all GET, return files)
/api/export/manifest, players.xlsx, bid-template, rosters.xlsx, roster-snapshots.json,
/api/export/lineups.csv, events.csv, standings.xlsx, athletics.xlsx, transfers.xlsx,
/api/export/prizes.csv, season.zip, auction/{n}/announcement.txt, auction/{n}/results.csv

# auction
POST /api/admin/auction/rounds
POST /api/admin/auction/rounds/{id}/submissions      (multipart, many files)
POST /api/admin/auction/rounds/{id}/resolve?dry_run=

# lineups
POST /api/lineups/validate
PUT  /api/lineups/{gameweek_id}/{manager_id}
GET  /api/lineups?gameweek=

# transfers & roster
POST /api/free-sign/{id}/revoke
POST /api/trades, /api/trades/{id}/(accept|reject|cancel)
POST /api/releases, /api/releases/{id}/revoke
POST /api/admin/dismissals, /api/admin/injuries, /api/admin/picks
GET/POST /api/admin/roster, POST /api/admin/roster/import?dry_run=
POST /api/admin/players/import, /api/admin/managers, /api/admin/windows, /api/admin/schedule

# events & gameweeks
GET/POST /api/admin/events, PUT/DELETE /api/admin/events/{id}
POST /api/admin/events/import?dry_run=
POST /api/admin/gameweeks/{id}/(live|finalize)
```

Conventions: every destructive/bulk write has `?dry_run=true` returning the same response shape as the real call; all writes stamp server time (never trust client clocks — matches `FreeSignService.try_propose` pattern); errors are engine exceptions passed through verbatim (`LineupError`, `XlsxBidParseError`, eligibility blocks) with HTTP 422.

## 6. Frontend architecture

- New pages: `Lineups.jsx`, `admin/AuctionDesk.jsx`, `admin/Events.jsx`, `admin/Gameweeks.jsx`, `admin/Roster.jsx`, `admin/Exports.jsx`, `admin/Setup.jsx`; shared: `PlayerSearch`, `ManagerPicker`, `DryRunDiff`, `DownloadCard`, `DeadlineCountdown`, `RoleGate`.
- Extend `src/api.js` with the endpoints above; add `download(path)` helper using `<a download>` with the auth header via fetch+blob.
- State stays server-driven (fetch-on-mount + refetch after writes, as today); no client store needed. Poll `/api/time` for countdowns.
- All rule numbers (caps, fees, min bid) come from API responses (which read `GameRules`) — the frontend hardcodes **nothing**, preserving the single-fact-source rule.
- i18n: labels bilingual-ready (zh keys for 暗标公示, 号 etc. already appear in exports); keep a small `strings.js` map rather than a full i18n lib for v1.

## 7. Build order

1. Export center (pure reads, immediate value; unblocks TODOs.md item 1)
2. Event fast-entry grid + gameweek finalize (unblocks scoring loop)
3. Lineup entry + validate preview
4. Auction desk (depends on cascade/tiebreaker implementations — top-priority stubs)
5. Trades/releases/dismissals/injuries, raw roster editor, season setup

Note: several backing services are still `NotImplementedError` stubs (cascade, tiebreaker, lineup caps, PK resolver, settle pipeline). The API layer above is designed so each frontend feature lights up as its service lands, with dry-run endpoints doubling as manual test harnesses for those implementations.
