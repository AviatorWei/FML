# FMLWC Web Frontend

A fantasy-football-style web app for the FMLWC engine. It has two parts:

- **`backend/`** — a FastAPI service that wraps the existing `fmlwc` engine and its
  SQLite database. It reuses the real `XlsxBidReader` and `FreeSignService`, so the
  web layer adds no new business logic.
- **`frontend/`** — a React + Vite + Tailwind single-page app.

## Pages

**Game reports & stats**

1. **Live Scores** (`/scores`) — live gameweek scores with auto-refresh, plus the
   result history of previous rounds (Live / History / All tabs).
2. **Standings** (`/standings`) — three views: **League** table, **Group Stage**
   tables (top 2 highlighted), and the knockout **Tournament** bracket.
3. **Player Scoreboard** (`/players`) — every player's scoring line, owner, auction
   price, and fantasy points; searchable and sortable by position/goals/assists/value.

**Bidding & signings**

4. **Upload Bids** (`/bids`) — drag-and-drop a sealed-bid `.xlsx`; the backend parses
   it into individual bids and checks the minimum-bid rule. Parsing only — no DB writes.
5. **Free Signings** (`/free-sign`) — look up a player, see auto-formatted
   position/club and free-agent status, watch the live **server clock**, and submit.
   The backend stamps the server time and runs the real free-sign validation against
   the configured transfer window. Pending signs can be **revoked** within the revoke
   window; "process due" commits signs whose window has elapsed.
6. **Lineups** (`/lineups`) — pick 8–10 starters per gameweek with slot caps
   (G≤1 D≤3 M≤4 F≤2), backward substitution (D→M/F, M→F), live rule-四 validation
   preview (accepted vs dropped), PK order, and deadline enforcement.

**Admin console** (needs the admin token — click 🔑 in the header; dev default
`fmlwc-admin`, override with the `FMLWC_ADMIN_TOKEN` env var)

7. **Auction Desk** (`/admin/auction`) — open rounds, drag in all managers'
   `FME_<year>_Bid<N>_<CODE>.xlsx` sheets, run a **dry-run resolve** (real cascade +
   tiebreaker, rolled back), inspect per-bid statuses and balance deltas, then commit
   and download the 暗标公示 announcement + results.
8. **Events** (`/admin/events`) — fast event entry keyed by (gameweek, player) with
   type chips, warnings (non-GK saved pen, shootout exclusion, not-in-lineup), live
   per-fixture valid-goal tally, and bulk CSV import (dry-run first).
9. **Gameweeks** (`/admin/gameweeks`) — create gameweeks/fixtures, set LIVE,
   **finalize** (writes MatchResults, runs bonuses + athletics fan-out via
   `RoundService`), record PK winners.
10. **Roster** (`/admin/roster`) — add/release/dismiss entries with engine
    eligibility checks, injury adjustments (refund + free-sign grant), trades with
    player/cash legs, KO picks, bulk roster import.
11. **Exports** (`/admin/exports`) — every artefact as a file: player list, bid
    templates, announcements, rosters, lineups, events, standings, athletics,
    transfer ledger, prizes, full season zip. See `/api/export/*`.

See `webapp/FRONTEND_DESIGN.md` for the design document and `webapp/mockup.html`
for the original static mockup.

## Run it

You need the Python env with the `fmlwc` package installed, plus Node 18+.

### 1. Generate data (once)

```bash
# from the project root
python scripts/run_auction.py --bids-dir example/bids-1 --round 1 --seed
python scripts/seed_demo.py        # groups, fixtures, demo results, transfer windows
```

### 2. Start the backend (port 8000)

```bash
pip install -e ".[webapp]"
# from the project root:
uvicorn webapp.backend.app:app --reload --port 8000
```

### 3. Start the frontend (port 5173)

```bash
cd webapp/frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend on
port 8000, so no CORS or env config is needed in development.

> **Note (switching OS):** `node_modules` contains platform-specific binaries
> (e.g. `@rollup/rollup-linux-x64-gnu` if it was installed on Linux). If
> `npm run dev` fails after moving the repo to another OS, delete
> `node_modules` and `package-lock.json`, then run `npm install` again.

### Production build

```bash
cd webapp/frontend
npm run build      # outputs to webapp/frontend/dist
npm run preview    # serve the build locally
```

To serve the built frontend from somewhere else, set `VITE_API_BASE` to the backend
URL at build time.

## API summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/time` | Server time (UTC + configured timezone) |
| GET | `/api/overview` | Scope, counts, key rule values |
| GET | `/api/managers` | Managers with balance, group, roster size |
| GET | `/api/standings/league` | League table |
| GET | `/api/standings/groups` | Per-group tables |
| GET | `/api/standings/tournament` | Knockout bracket |
| GET | `/api/scores/gameweeks` | Gameweek list + status |
| GET | `/api/scores?status=&gameweek=` | Fixtures + results |
| GET | `/api/players?q=&position=&sort=` | Player scoreboard |
| GET | `/api/players/search?q=` | Free-sign player lookup |
| GET | `/api/auction/results?round_index=` | Auction awards |
| POST | `/api/bids/upload` | Parse a bid `.xlsx` (multipart) |
| GET | `/api/transfer/windows` | Windows + which is open now |
| POST | `/api/free-sign` | Propose a free signing |
| GET | `/api/free-sign/list` | Recent free signings |
| POST | `/api/free-sign/{id}/revoke` | Revoke within the revoke window |
| POST | `/api/free-sign/commit-due` | Commit signs past the revoke window |
| GET | `/api/lineups?gameweek=` | Submitted lineups |
| POST | `/api/lineups/validate` | Rule-四 validation preview (no write) |
| PUT | `/api/lineups/{gw}/{manager}` | Submit lineup (deadline-checked) |
| GET | `/api/export/manifest` | Row counts for the export center |
| GET | `/api/export/…` | Files: players/rosters/lineups/events/standings/athletics/transfers/prizes/season.zip, auction announcement + results, bid templates |

| POST | `/api/releases` | Propose a release (pending, rule 八) |
| POST | `/api/releases/{id}/revoke` | Revoke within the release revoke window |
| POST | `/api/releases/commit-due` | Commit releases past the window (refund + lifetime block) |
| GET | `/api/releases/list` | Release ledger |
| GET | `/api/cup/status` | Dual-competition mode: teams, separation state |
| GET/POST | `/api/cup/assignments` | Declare which competition a dual player counts for |

Admin endpoints (all under `/api/admin/*`, require `X-Admin-Token`):
auction `rounds` / `submissions` / `resolve?dry_run=`, `events` (+ `import`,
`tally`), `gameweeks` (+ `fixtures`, `live`, `finalize?dry_run=`, `pk-winner`),
`roster` (+ `release`, `import`), `dismissals`, `injuries`, `trades` (+
`accept|reject|cancel`), `picks` (+ `picks/snapshot`), `managers`, `windows`,
`players/import`.

**Dual-competition (league + cup) mode** — see `config/rules.fml-fmc.example.yaml`
and `COMPLIANCE.md` (rule-by-rule matrix for league-only / league+cup /
customized-cup). Gameweeks carry a competition (LEAGUE/CUP); league standings
count only LEAGUE results, the bracket only CUP results, and the reserve
(预备队) table lives at `/api/standings/reserve`. Cup semantics per FMC
第七十七/七十八条: during the cup group stage there is ONE shared roster (dual
players float, operations hit both games); when the first CUP knockout
gameweek goes LIVE the cup list forks (`/api/cup/separate` for manual) and
league/cup operations become independent. Cup-exclusive players are paid from
the manager's cup wallet, which during the group stage may only sign them.
Engine logic: `fmlwc/domain/competition.py`; design: `DESIGN.md` §9.

**Conventions:** destructive/bulk endpoints support `?dry_run=true` (real engine
code inside a transaction, then rollback); all writes stamp server time; engine
errors pass through verbatim as 409/422; endpoints backed by still-stubbed
services return 501 with the stub's TODO message.

## Notes

- The `tournament` bracket fills quarterfinal slots from group standings; semifinal
  and final pairings appear once knockout results are entered into the DB.
- `scripts/seed_demo.py` creates **demo** match results and player stats (seeded RNG)
  so the score/stat pages are populated. Re-running it regenerates the same dataset.
  Real match data entered through the engine will display the same way.
