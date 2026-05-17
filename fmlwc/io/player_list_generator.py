"""Player list generator for FMLWC.

Builds the initial player catalogue from Transfermarkt squad pages for a
major international tournament (e.g. Euro 2020).

The HTTP + HTML-parsing implementation is intentionally left as a stub —
implement ``_scrape_team_page`` when you are ready to pull live data.

ID strategies
-------------
``IdMode.FROM_URL``
    Extract the numeric Transfermarkt player id from the profile URL,
    e.g. ``https://www.transfermarkt.com/manuel-neuer/profil/spieler/17259``
    → ``17259``.  IDs are stable across seasons and globally unique.

``IdMode.SEQUENTIAL``
    Assign compact sequential integers starting from ``seq_start`` (default 1),
    ordered by (team index in the input list, jersey number, name).
    This matches the short "号" IDs used in the existing auction xlsx files.

Injection targets
-----------------
``inject_into_session(players, session)``
    Upserts ``Player`` ORM rows into a live SQLAlchemy ``Session``.
    The caller is responsible for ``session.commit()``.

``inject_into_fake_repo(players, repo)``
    Writes ``FakePlayer`` objects into a ``FakePlayerRepo``.
    Used by demo scripts and test fixtures.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.enums import Position

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ...tests.fakes import FakePlayerRepo


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamConfig:
    """One national-team entry to scrape."""
    code: str        # short code stored as Player.real_team, e.g. "GER"
    squad_url: str   # Transfermarkt squad-page URL for this team + season


# Euro 2020 (played 2021) — 24 participating teams.
# Transfermarkt national-team squad URLs follow the pattern:
#   https://www.transfermarkt.com/<slug>/kader/verein/<tm_id>/saison_id/2020
# Fill in the correct <slug> and <tm_id> for each team before scraping.
EURO_2020_TEAMS: list[TeamConfig] = [
    # Group A
    TeamConfig("TUR", "https://www.transfermarkt.com/turkei/kader/verein/792/saison_id/2020"),
    TeamConfig("ITA", "https://www.transfermarkt.com/italien/kader/verein/788/saison_id/2020"),
    TeamConfig("WAL", "https://www.transfermarkt.com/wales/kader/verein/833/saison_id/2020"),
    TeamConfig("SUI", "https://www.transfermarkt.com/schweiz/kader/verein/806/saison_id/2020"),
    # Group B
    TeamConfig("DEN", "https://www.transfermarkt.com/danemark/kader/verein/782/saison_id/2020"),
    TeamConfig("FIN", "https://www.transfermarkt.com/finnland/kader/verein/1736/saison_id/2020"),
    TeamConfig("BEL", "https://www.transfermarkt.com/belgien/kader/verein/781/saison_id/2020"),
    TeamConfig("RUS", "https://www.transfermarkt.com/russland/kader/verein/803/saison_id/2020"),
    # Group C
    TeamConfig("NED", "https://www.transfermarkt.com/niederlande/kader/verein/796/saison_id/2020"),
    TeamConfig("UKR", "https://www.transfermarkt.com/ukraine/kader/verein/812/saison_id/2020"),
    TeamConfig("AUT", "https://www.transfermarkt.com/osterreich/kader/verein/779/saison_id/2020"),
    TeamConfig("MKD", "https://www.transfermarkt.com/nordmazedonien/kader/verein/1071/saison_id/2020"),
    # Group D
    TeamConfig("ENG", "https://www.transfermarkt.com/england/kader/verein/3/saison_id/2020"),
    TeamConfig("CRO", "https://www.transfermarkt.com/kroatien/kader/verein/3583/saison_id/2020"),
    TeamConfig("SCO", "https://www.transfermarkt.com/schottland/kader/verein/804/saison_id/2020"),
    TeamConfig("CZE", "https://www.transfermarkt.com/tschechien/kader/verein/782/saison_id/2020"),
    # Group E
    TeamConfig("ESP", "https://www.transfermarkt.com/spanien/kader/verein/785/saison_id/2020"),
    TeamConfig("SWE", "https://www.transfermarkt.com/schweden/kader/verein/805/saison_id/2020"),
    TeamConfig("POL", "https://www.transfermarkt.com/polen/kader/verein/800/saison_id/2020"),
    TeamConfig("SVK", "https://www.transfermarkt.com/slowakei/kader/verein/1304/saison_id/2020"),
    # Group F
    TeamConfig("HUN", "https://www.transfermarkt.com/ungarn/kader/verein/787/saison_id/2020"),
    TeamConfig("POR", "https://www.transfermarkt.com/portugal/kader/verein/801/saison_id/2020"),
    TeamConfig("FRA", "https://www.transfermarkt.com/frankreich/kader/verein/3377/saison_id/2020"),
    TeamConfig("GER", "https://www.transfermarkt.com/deutschland/kader/verein/3262/saison_id/2020"),
]


# ---------------------------------------------------------------------------
# Raw data shape returned by the scraper
# ---------------------------------------------------------------------------

@dataclass
class RawPlayer:
    """Player data as extracted from one squad-page row before ID assignment."""
    name: str
    jersey_no: int | None     # shirt number; None if not listed
    position_raw: str         # position string as it appears on the website
    real_team: str            # team code from TeamConfig.code
    market_value_eur_m: int   # market value in M EUR (0 if not listed)
    profile_url: str | None   # full Transfermarkt profile URL — required for IdMode.FROM_URL


# ---------------------------------------------------------------------------
# ID strategy
# ---------------------------------------------------------------------------

class IdMode(str, enum.Enum):
    FROM_URL   = "from_url"   # extract numeric id from profile_url
    SEQUENTIAL = "sequential" # assign 1, 2, 3 … in iteration order


# ---------------------------------------------------------------------------
# Position normalisation
# ---------------------------------------------------------------------------

# Transfermarkt uses verbose English position labels; map them to G/D/M/F.
_POSITION_MAP: dict[str, Position] = {
    # Goalkeepers
    "goalkeeper": Position.G,
    "gk":         Position.G,
    # Defenders
    "centre-back":      Position.D,
    "center-back":      Position.D,
    "left-back":        Position.D,
    "right-back":       Position.D,
    "left back":        Position.D,
    "right back":       Position.D,
    "defender":         Position.D,
    "cb":               Position.D,
    "lb":               Position.D,
    "rb":               Position.D,
    # Midfielders
    "central midfield":    Position.M,
    "defensive midfield":  Position.M,
    "attacking midfield":  Position.M,
    "left midfield":       Position.M,
    "right midfield":      Position.M,
    "midfielder":          Position.M,
    "cm":                  Position.M,
    "cdm":                 Position.M,
    "cam":                 Position.M,
    "lm":                  Position.M,
    "rm":                  Position.M,
    # Forwards
    "centre-forward":   Position.F,
    "center-forward":   Position.F,
    "left winger":      Position.F,
    "right winger":     Position.F,
    "second striker":   Position.F,
    "forward":          Position.F,
    "striker":          Position.F,
    "cf":               Position.F,
    "lw":               Position.F,
    "rw":               Position.F,
    "ss":               Position.F,
    # Single-letter fallbacks (already in our enum)
    "g": Position.G,
    "d": Position.D,
    "m": Position.M,
    "f": Position.F,
}


def normalise_position(raw: str) -> Position:
    """Map a raw position string to a ``Position`` enum value.

    Falls back to ``Position.M`` (midfielder) for unrecognised strings so
    that partial data does not abort a full import — callers should log
    unrecognised values and fix the mapping.
    """
    key = raw.strip().lower()
    return _POSITION_MAP.get(key, Position.M)


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

_TM_ID_RE = re.compile(r"/spieler/(\d+)", re.IGNORECASE)


def _id_from_profile_url(url: str) -> int:
    """Extract the numeric Transfermarkt player id from a profile URL.

    Raises ``ValueError`` if the URL does not contain ``/spieler/<id>``.
    """
    m = _TM_ID_RE.search(url)
    if not m:
        raise ValueError(
            f"Cannot extract Transfermarkt player id from URL: {url!r}. "
            "Expected a path segment like /spieler/17259."
        )
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Scraper stub
# ---------------------------------------------------------------------------

def _scrape_team_page(config: TeamConfig, http_session=None) -> list[RawPlayer]:
    """Fetch and parse one Transfermarkt squad page.

    **NOT IMPLEMENTED** — this is a stub.  Replace this function body with
    real HTTP + HTML-parsing code when you are ready to scrape.

    Implementation notes
    ~~~~~~~~~~~~~~~~~~~~
    Transfermarkt squad pages (``/kader/…``) render a responsive table where
    each player row (``<tr class="odd">``, ``<tr class="even">``) contains:

    * ``td.rn_nummer``      — jersey number
    * ``td.posrela``        — position abbreviation (e.g. "LB", "CAM")
    * ``td.hauptlink a``    — player name (text) and profile href
    * ``td.rechts``         — market value (e.g. "€45.00m", "€850k")

    Example with requests + BeautifulSoup::

        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0 (compatible; FMLWC-scraper/0.1)"}
        resp = http_session.get(config.squad_url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table.items tbody tr.odd, table.items tbody tr.even")
        players = []
        for row in rows:
            name_tag  = row.select_one("td.hauptlink a")
            pos_tag   = row.select_one("td.posrela")
            no_tag    = row.select_one("td.rn_nummer")
            val_tag   = row.select_one("td.rechts")
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
    """
    raise NotImplementedError(
        f"_scrape_team_page is a stub. "
        f"Implement HTTP + HTML parsing to scrape {config.squad_url!r}."
    )


def _parse_market_value(text: str) -> int:
    """Convert a Transfermarkt market-value string to integer millions EUR.

    Examples: ``"€45.00m"`` → 45, ``"€850k"`` → 1 (rounded), ``"-"`` → 0.
    """
    text = text.strip().lstrip("€").replace(",", "")
    if not text or text in ("-", "N/A", "n/a"):
        return 0
    m = re.fullmatch(r"([\d.]+)\s*([mk]?)", text, re.IGNORECASE)
    if not m:
        return 0
    value, suffix = float(m.group(1)), m.group(2).lower()
    if suffix == "m":
        return round(value)
    if suffix == "k":
        return max(1, round(value / 1000))
    return round(value)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class PlayerListGenerator:
    """Orchestrates scraping + ID assignment for a list of teams.

    Parameters
    ----------
    teams:
        Ordered list of ``TeamConfig`` entries to scrape.  Teams are
        processed in order; when ``id_mode=SEQUENTIAL``, the ordering
        determines which player gets which integer id.
    id_mode:
        How to assign ``Player.id`` — see module docstring.
    seq_start:
        First sequential id to assign (only used for ``IdMode.SEQUENTIAL``).
    """

    def __init__(
        self,
        teams: list[TeamConfig],
        id_mode: IdMode = IdMode.SEQUENTIAL,
        seq_start: int = 1,
    ) -> None:
        self.teams = teams
        self.id_mode = id_mode
        self.seq_start = seq_start

    def generate(self, http_session=None) -> list[tuple[int, RawPlayer]]:
        """Scrape all teams and return ``(player_id, RawPlayer)`` pairs.

        Parameters
        ----------
        http_session:
            Optional ``requests.Session`` (or compatible object) passed
            through to the scraper for connection pooling and cookie
            handling.  ``None`` is fine until ``_scrape_team_page`` is
            implemented.

        Returns
        -------
        list of ``(player_id, RawPlayer)`` sorted by player_id ascending.
        """
        raw_players: list[RawPlayer] = []
        for config in self.teams:
            team_players = _scrape_team_page(config, http_session)
            # sort within each team: jersey number first, then name
            team_players.sort(key=lambda p: (p.jersey_no or 999, p.name))
            raw_players.extend(team_players)

        if self.id_mode is IdMode.FROM_URL:
            return self._assign_from_url(raw_players)
        return self._assign_sequential(raw_players)

    def _assign_from_url(
        self, players: list[RawPlayer]
    ) -> list[tuple[int, RawPlayer]]:
        result: list[tuple[int, RawPlayer]] = []
        seen: set[int] = set()
        for p in players:
            if not p.profile_url:
                raise ValueError(
                    f"Player {p.name!r} ({p.real_team}) has no profile_url; "
                    "IdMode.FROM_URL requires every player to have one."
                )
            pid = _id_from_profile_url(p.profile_url)
            if pid in seen:
                raise ValueError(
                    f"Duplicate Transfermarkt id {pid} for player {p.name!r}."
                )
            seen.add(pid)
            result.append((pid, p))
        result.sort(key=lambda t: t[0])
        return result

    def _assign_sequential(
        self, players: list[RawPlayer]
    ) -> list[tuple[int, RawPlayer]]:
        return [(self.seq_start + i, p) for i, p in enumerate(players)]


# ---------------------------------------------------------------------------
# Injection helpers
# ---------------------------------------------------------------------------

def inject_into_session(
    players: list[tuple[int, RawPlayer]],
    session: "Session",
) -> int:
    """Upsert ``Player`` ORM rows into a SQLAlchemy session.

    Uses a merge-or-insert strategy: if a row with the same ``id`` already
    exists it is updated in-place; otherwise a new row is inserted.  The
    caller is responsible for ``session.commit()``.

    Returns the number of rows written.
    """
    from ..persistence.models.people import Player

    for player_id, raw in players:
        existing = session.get(Player, player_id)
        if existing is not None:
            existing.name         = raw.name
            existing.jersey_no    = raw.jersey_no
            existing.position     = normalise_position(raw.position_raw)
            existing.real_team    = raw.real_team
            existing.market_value = raw.market_value_eur_m
        else:
            session.add(Player(
                id=player_id,
                name=raw.name,
                jersey_no=raw.jersey_no,
                position=normalise_position(raw.position_raw),
                real_team=raw.real_team,
                market_value=raw.market_value_eur_m,
            ))

    return len(players)


def inject_into_fake_repo(
    players: list[tuple[int, RawPlayer]],
    repo: "FakePlayerRepo",
) -> int:
    """Write players into a ``FakePlayerRepo`` for use in tests / demo scripts.

    Existing entries with the same id are overwritten.

    Returns the number of rows written.
    """
    from tests.fakes import FakePlayer

    for player_id, raw in players:
        repo.players[player_id] = FakePlayer(
            id=player_id,
            name=raw.name,
            position=normalise_position(raw.position_raw),
            real_team=raw.real_team,
            market_value=raw.market_value_eur_m,
            jersey_no=raw.jersey_no,
        )
    return len(players)
