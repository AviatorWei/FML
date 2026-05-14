"""Tests for fmlwc.io.announcement.AuctionAnnouncementFormatter.

Round-trip tests: parse the canonical example files into BidAnnouncementRow
objects, then verify the formatter reproduces the file verbatim.

Note on round-2 data quality
-----------------------------
Several rows in ``2轮暗标公示.txt`` carry float-formatted player IDs (e.g.
``19.0号``) — an Excel artefact where the source xlsx stored the jersey
number as a float.  Our ORM uses integer player_id.  Both the parser and
the round-trip comparison normalise ``N.0号`` → ``N号`` so the formatter
is tested against canonically clean data.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fmlwc.domain.auction.service import BidAnnouncementRow
from fmlwc.core.enums import BidStatus
from fmlwc.io.announcement import AuctionAnnouncementFormatter

EXAMPLE_DIR = Path(__file__).parent.parent / "example"


# ---------------------------------------------------------------------------
# Parser: txt → list[BidAnnouncementRow]
# ---------------------------------------------------------------------------

# Matches lines like:
#   1   131m Havertz             M  GER         7号  GEO
#   4   15m  Musiala             M  GER         10号 ENG
#   1   30m  Sane                F  GER         19.0号 GER   ← float pid (round-2 artefact)
#
# Groups: rank | amount | name | pos | team | player_id_str | manager
_LINE_RE = re.compile(
    r"^(\d+)"                  # rank_in_position
    r"\s+"
    r"(\d+)m"                  # amount (integer before 'm')
    r"\s+"
    r"(.+?)"                   # player_name (non-greedy)
    r"\s+"
    r"([GDMF])"                # position
    r"\s+"
    r"([A-Z]{2,4})"            # real_team
    r"\s+"
    r"(\d+(?:\.\d+)?)号"        # player_id, optional decimal (e.g. 19.0)
    r"\s+"
    r"([A-Z]{2,4})"            # manager_code
    r"\s*$"
)


def _to_int_pid(pid_str: str) -> int:
    """Convert '19.0' or '19' to 19."""
    return int(float(pid_str))


def _parse_announcement(path: Path) -> list[BidAnnouncementRow]:
    """Parse a 暗标公示 txt file into BidAnnouncementRow objects.

    Blank lines (player separators) are skipped.  Float player IDs (Excel
    artefact) are normalised to int.
    """
    rows: list[BidAnnouncementRow] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        m = _LINE_RE.match(raw_line)
        if m is None:
            raise ValueError(f"Cannot parse line: {raw_line!r}")
        rank, amount, name, pos, team, pid_str, mgr = m.groups()
        rows.append(
            BidAnnouncementRow(
                player_id=_to_int_pid(pid_str),
                player_name=name.strip(),
                position=pos,
                real_team=team,
                rank_in_position=int(rank),
                amount=int(amount),
                manager_code=mgr,
                status=BidStatus.LOST,   # status does not affect formatting
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_FLOAT_PID_RE = re.compile(r"(\d+)\.0号")

def _normalise(text: str) -> str:
    """Strip trailing whitespace; collapse float IDs; single trailing newline."""
    # Normalise float player IDs: '19.0号' → '19号'
    text = _FLOAT_PID_RE.sub(r"\1号", text)
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def _first_diff(expected: str, actual: str) -> str:
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            return f"  line {i + 1}\n  expected: {e!r}\n  got:      {a!r}"
    if len(exp_lines) != len(act_lines):
        return f"  line count: expected {len(exp_lines)}, got {len(act_lines)}"
    return "  (no difference found)"


# ---------------------------------------------------------------------------
# Unit tests: _format_line spacing
# ---------------------------------------------------------------------------

class TestFormatLine:
    FMT = AuctionAnnouncementFormatter()

    def _row(self, pid, amount, rank=1, name="Neuer", pos="G", team="GER", mgr="ITA"):
        return BidAnnouncementRow(
            player_id=pid, player_name=name, position=pos, real_team=team,
            rank_in_position=rank, amount=amount, manager_code=mgr,
            status=BidStatus.AWARDED,
        )

    def test_single_digit_pid_has_two_spaces_after_hao(self):
        line = self.FMT._format_line(self._row(1, 10))
        assert "1号  ITA" in line

    def test_two_digit_pid_has_one_space_after_hao(self):
        line = self.FMT._format_line(self._row(10, 15, mgr="ENG"))
        assert "10号 ENG" in line

    def test_three_digit_pid_has_one_space_after_hao(self):
        line = self.FMT._format_line(self._row(105, 12, mgr="ALB"))
        assert "105号 ALB" in line

    def test_amount_left_justified_5_short(self):
        # "10m" padded to width 5 → "10m  "
        line = self.FMT._format_line(self._row(1, 10))
        assert "10m  " in line

    def test_amount_left_justified_5_long(self):
        # "131m" padded to width 5 → "131m "
        line = self.FMT._format_line(self._row(7, 131, mgr="GEO"))
        assert "131m " in line

    def test_name_left_justified_20(self):
        line = self.FMT._format_line(self._row(1, 10))
        assert "Neuer               " in line

    def test_exact_line_single_digit_pid(self):
        """Exact reproduction of a line from 1轮暗标公示.txt."""
        row = self._row(pid=1, amount=10, rank=1, name="Neuer", pos="G", team="GER", mgr="ITA")
        assert self.FMT._format_line(row) == "1   10m  Neuer               G  GER         1号  ITA"

    def test_exact_line_two_digit_pid(self):
        """Two-digit player_id line from 1轮暗标公示.txt."""
        row = BidAnnouncementRow(
            player_id=10, player_name="Musiala", position="M",
            real_team="GER", rank_in_position=4, amount=15,
            manager_code="ENG", status=BidStatus.LOST,
        )
        assert self.FMT._format_line(row) == "4   15m  Musiala             M  GER         10号 ENG"

    def test_exact_line_three_digit_pid(self):
        """Three-digit player_id line from 1轮暗标公示.txt."""
        row = BidAnnouncementRow(
            player_id=105, player_name="E.Berisha", position="G",
            real_team="ALB", rank_in_position=1, amount=12,
            manager_code="ALB", status=BidStatus.AWARDED,
        )
        assert self.FMT._format_line(row) == "1   12m  E.Berisha           G  ALB         105号 ALB"

    def test_exact_line_three_digit_bid_131m(self):
        """131m amount + two-digit pid from 1轮暗标公示.txt."""
        row = BidAnnouncementRow(
            player_id=7, player_name="Havertz", position="M",
            real_team="GER", rank_in_position=1, amount=131,
            manager_code="GEO", status=BidStatus.AWARDED,
        )
        assert self.FMT._format_line(row) == "1   131m Havertz             M  GER         7号  GEO"


# ---------------------------------------------------------------------------
# Unit tests: block structure
# ---------------------------------------------------------------------------

class TestFormatStructure:
    FMT = AuctionAnnouncementFormatter()

    def _row(self, pid, amount, rank=1, mgr="ITA"):
        return BidAnnouncementRow(
            player_id=pid, player_name="X", position="F", real_team="AAA",
            rank_in_position=rank, amount=amount, manager_code=mgr,
            status=BidStatus.LOST,
        )

    def test_empty_returns_empty_string(self):
        assert self.FMT.format([]) == ""

    def test_single_player_no_blank_line(self):
        rows = [self._row(1, 30, mgr="ITA"), self._row(1, 20, mgr="POR")]
        text = self.FMT.format(rows)
        assert "\n\n" not in text
        assert text.count("\n") == 2   # 2 lines + trailing newline

    def test_two_players_separated_by_blank_line(self):
        rows = [self._row(1, 30), self._row(2, 20)]
        text = self.FMT.format(rows)
        assert "\n\n" in text

    def test_trailing_newline(self):
        rows = [self._row(1, 10)]
        assert self.FMT.format(rows).endswith("\n")

    def test_within_player_input_order_preserved(self):
        """Formatter preserves input order (caller is responsible for sorting)."""
        rows = [
            self._row(7, 131, mgr="GEO"),
            self._row(7, 120, mgr="GER"),
            self._row(7, 101, mgr="NED"),
        ]
        lines = [l for l in self.FMT.format(rows).splitlines() if l.strip()]
        assert "GEO" in lines[0]
        assert "GER" in lines[1]
        assert "NED" in lines[2]


# ---------------------------------------------------------------------------
# Round-trip tests against historical example files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", ["1轮暗标公示.txt", "2轮暗标公示.txt"])
def test_round_trip(filename: str) -> None:
    """Parse example file → format → compare to original (after normalisation).

    The formatter must reproduce every line exactly.  For round-2, float
    player IDs (``19.0号``) are normalised to integer form (``19号``) in
    both the expected and actual text before comparison.
    """
    path = EXAMPLE_DIR / filename
    if not path.exists():
        pytest.skip(f"Example file not found: {path}")

    original = _normalise(path.read_text(encoding="utf-8"))
    rows = _parse_announcement(path)

    # announcement_views() returns rows sorted: player_id asc, amount desc
    rows.sort(key=lambda r: (r.player_id, -r.amount))

    result = _normalise(AuctionAnnouncementFormatter().format(rows))
    assert result == original, (
        f"Formatter output does not match {filename}.\n"
        f"First differing line:\n"
        + _first_diff(original, result)
    )
