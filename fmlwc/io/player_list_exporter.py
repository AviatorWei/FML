"""Player-list xlsx exporter.

Produces a spreadsheet in the same format as ``FME_2024_Bid2_XXX.xlsx``:

    ID | Name | Nation | Pos | Team | Price

where *Team* and *Price* are ``None`` for unowned (free-agent) players.

Typical usage::

    from fmlwc.io.player_list_exporter import PlayerListExporter, query_player_list
    from fmlwc.persistence.db import make_engine, make_session_factory, session_scope

    engine  = make_engine("sqlite:///fmlwc.db")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        rows = query_player_list(session)

    PlayerListExporter().write(rows, "player_list.xlsx")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# View object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerListRow:
    """One row of the player-list spreadsheet."""
    player_id: int
    name: str
    nation: str             # real_team abbreviation, e.g. "GER"
    position: str           # "G" | "D" | "M" | "F"
    manager_code: str | None = None   # display_name of current owner; None = free agent
    price: int | None = None          # acquired_price in M EUR; None = free agent


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

_HEADERS = ("ID", "Name", "Nation", "Pos", "Team", "Price")


class PlayerListExporter:
    """Writes a list of ``PlayerListRow`` objects to an xlsx file.

    Parameters
    ----------
    sheet_name:
        Name of the single worksheet.  Defaults to ``"Sheet1"`` to match
        the reference file format.
    """

    def __init__(self, sheet_name: str = "Sheet1") -> None:
        self.sheet_name = sheet_name

    def write(self, rows: list[PlayerListRow], path: Path | str) -> None:
        """Serialise *rows* to *path*.

        Rows are written in the order supplied; call site is responsible for
        sorting (typically by player_id ascending).

        Raises
        ------
        ImportError
            If *openpyxl* is not installed.
        """
        try:
            import openpyxl
        except ImportError as exc:
            raise ImportError(
                "openpyxl is required to write xlsx files: pip install openpyxl"
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.sheet_name

        ws.append(list(_HEADERS))
        for r in rows:
            ws.append([
                r.player_id,
                r.name,
                r.nation,
                r.position,
                r.manager_code,
                r.price,
            ])

        wb.save(path)


# ---------------------------------------------------------------------------
# SQL helper
# ---------------------------------------------------------------------------

def query_player_list(session: "Session") -> list[PlayerListRow]:
    """Return one ``PlayerListRow`` per player, sorted by player_id.

    A LEFT JOIN is used so free-agent players appear with ``manager_code``
    and ``price`` set to ``None``.  Only the *current* roster entry is
    joined (``released_at IS NULL``).
    """
    from sqlalchemy import text

    sql = text("""
        SELECT
            p.id            AS player_id,
            p.name          AS name,
            p.real_team     AS nation,
            p.position      AS position,
            m.display_name  AS manager_code,
            r.acquired_price AS price
        FROM players p
        LEFT JOIN roster_entries r
            ON r.player_id = p.id AND r.released_at IS NULL
        LEFT JOIN managers m
            ON m.id = r.manager_id
        ORDER BY p.id
    """)

    result = session.execute(sql)
    return [
        PlayerListRow(
            player_id=row.player_id,
            name=row.name,
            nation=row.nation,
            position=row.position,
            manager_code=row.manager_code,
            price=row.price,
        )
        for row in result
    ]
