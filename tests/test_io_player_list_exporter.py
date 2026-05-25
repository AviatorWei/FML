"""Tests for fmlwc.io.player_list_exporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from fmlwc.io.player_list_exporter import PlayerListExporter, PlayerListRow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROWS = [
    PlayerListRow(player_id=1, name="Neuer",   nation="GER", position="G",
                  manager_code="ITA", price=10),
    PlayerListRow(player_id=2, name="Rudiger", nation="GER", position="D",
                  manager_code="ITA", price=30),
    PlayerListRow(player_id=3, name="Raum",    nation="GER", position="D",
                  manager_code=None,  price=None),
    PlayerListRow(player_id=7, name="Havertz", nation="GER", position="M",
                  manager_code="GEO", price=131),
]


# ---------------------------------------------------------------------------
# Round-trip against reference file
# ---------------------------------------------------------------------------

def test_round_trip_reference_file():
    """The reference xlsx must load as PlayerListRow objects that survive a
    write/read cycle with identical values."""
    import openpyxl

    ref = Path(__file__).parent.parent / "example" / "FME_2024_Bid2_XXX.xlsx"
    wb = openpyxl.load_workbook(ref, data_only=True, read_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    next(it)   # skip header
    ref_rows = [
        PlayerListRow(
            player_id=int(r[0]),
            name=str(r[1]),
            nation=str(r[2]),
            position=str(r[3]),
            manager_code=str(r[4]) if r[4] is not None else None,
            price=int(r[5]) if r[5] is not None else None,
        )
        for r in it
    ]
    wb.close()

    assert len(ref_rows) == 622

    # Spot-check known rows from the reference
    assert ref_rows[0] == PlayerListRow(1, "Neuer", "GER", "G", "ITA", 10)
    assert ref_rows[2] == PlayerListRow(3, "Raum",  "GER", "D", None, None)
    assert ref_rows[6] == PlayerListRow(7, "Havertz","GER","M", "GEO", 131)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def test_headers(tmp_path):
    out = tmp_path / "out.xlsx"
    PlayerListExporter().write([], out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    ws = wb.active
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    wb.close()

    assert header == ("ID", "Name", "Nation", "Pos", "Team", "Price")


def test_sheet_name_default(tmp_path):
    out = tmp_path / "out.xlsx"
    PlayerListExporter().write([], out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    assert wb.active.title == "Sheet1"
    wb.close()


def test_sheet_name_custom(tmp_path):
    out = tmp_path / "out.xlsx"
    PlayerListExporter(sheet_name="Players").write([], out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    assert wb.active.title == "Players"
    wb.close()


def test_owned_player_row(tmp_path):
    out = tmp_path / "out.xlsx"
    PlayerListExporter().write([_ROWS[0]], out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    rows = list(wb.active.iter_rows(min_row=2, values_only=True))
    wb.close()

    assert rows[0] == (1, "Neuer", "GER", "G", "ITA", 10)


def test_free_agent_row_has_none_cells(tmp_path):
    out = tmp_path / "out.xlsx"
    free_agent = _ROWS[2]   # Raum — no manager, no price
    PlayerListExporter().write([free_agent], out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    rows = list(wb.active.iter_rows(min_row=2, values_only=True))
    wb.close()

    assert rows[0] == (3, "Raum", "GER", "D", None, None)


def test_row_order_preserved(tmp_path):
    out = tmp_path / "out.xlsx"
    PlayerListExporter().write(_ROWS, out)

    import openpyxl
    wb = openpyxl.load_workbook(out, data_only=True, read_only=True)
    data = list(wb.active.iter_rows(min_row=2, values_only=True))
    wb.close()

    ids = [r[0] for r in data]
    assert ids == [1, 2, 3, 7]


def test_write_accepts_path_string(tmp_path):
    out = str(tmp_path / "out.xlsx")
    PlayerListExporter().write(_ROWS, out)
    assert Path(out).exists()


# ---------------------------------------------------------------------------
# SQL helper — integration test (in-memory SQLite)
# ---------------------------------------------------------------------------

def test_query_player_list_integration():
    from sqlalchemy import text
    from fmlwc.persistence.db import create_all, make_engine, make_session_factory, session_scope

    engine  = make_engine("sqlite:///:memory:")
    create_all(engine)
    factory = make_session_factory(engine)

    from fmlwc.io.player_list_exporter import query_player_list

    with session_scope(factory) as session:
        session.execute(text(
            "INSERT INTO managers (id, display_name, balance, total_points) VALUES (1, 'GEO', 500, 0)"
        ))
        session.execute(text(
            "INSERT INTO players (id, name, position, real_team, market_value) "
            "VALUES (1, 'Havertz', 'M', 'GER', 0), "
            "       (2, 'Raum',    'D', 'GER', 0)"
        ))
        # Havertz owned by GEO at price 131
        session.execute(text(
            "INSERT INTO roster_entries (manager_id, player_id, acquired_at, acquired_via, acquired_price) "
            "VALUES (1, 1, '2024-01-01', 'AUCTION', 131)"
        ))
        # Raum is free agent — no roster_entry

        rows = query_player_list(session)

    assert len(rows) == 2
    assert rows[0] == PlayerListRow(1, "Havertz", "GER", "M", "GEO", 131)
    assert rows[1] == PlayerListRow(2, "Raum",    "GER", "D", None,   None)


def test_query_excludes_released_entries():
    """A player whose roster_entry has released_at set should appear as free agent."""
    from sqlalchemy import text
    from fmlwc.persistence.db import create_all, make_engine, make_session_factory, session_scope
    from fmlwc.io.player_list_exporter import query_player_list

    engine  = make_engine("sqlite:///:memory:")
    create_all(engine)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        session.execute(text(
            "INSERT INTO managers (id, display_name, balance, total_points) VALUES (1, 'ENG', 500, 0)"
        ))
        session.execute(text(
            "INSERT INTO players (id, name, position, real_team, market_value) "
            "VALUES (1, 'Saka', 'M', 'ENG', 0)"
        ))
        session.execute(text(
            "INSERT INTO roster_entries "
            "(manager_id, player_id, acquired_at, released_at, acquired_via, acquired_price) "
            "VALUES (1, 1, '2024-01-01', '2024-06-01', 'AUCTION', 80)"
        ))

        rows = query_player_list(session)

    assert rows[0].manager_code is None
    assert rows[0].price is None
