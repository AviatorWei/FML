"""Tests for fmlwc.io.xlsx_bid_reader."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fmlwc.io.xlsx_bid_reader import (
    DEFAULT_FILENAME_PATTERN,
    DEFAULT_HEADERS,
    BidRow,
    XlsxBidParseError,
    XlsxBidReader,
    XlsxSubmission,
)
from fmlwc.domain.auction.bids import RawBid

BIDS_1_DIR = Path(__file__).parent.parent / "example" / "bids-1"


def _reader() -> XlsxBidReader:
    """Default reader pointed at the bids-1 example folder."""
    return XlsxBidReader(BIDS_1_DIR)


# ---------------------------------------------------------------------------
# Constructor / configuration
# ---------------------------------------------------------------------------

class TestInit:
    def test_stores_directory(self):
        r = XlsxBidReader(BIDS_1_DIR)
        assert r.directory == BIDS_1_DIR

    def test_default_pattern(self):
        r = XlsxBidReader(BIDS_1_DIR)
        assert r.filename_pattern == DEFAULT_FILENAME_PATTERN

    def test_default_headers(self):
        r = XlsxBidReader(BIDS_1_DIR)
        assert r.expected_headers == DEFAULT_HEADERS

    def test_custom_pattern_string_is_compiled(self):
        custom = r'^FME_\d{4}_Bid(\d+)_([A-Z]{2,4})\.xlsx$'
        r = XlsxBidReader(BIDS_1_DIR, filename_pattern=custom)
        assert isinstance(r.filename_pattern, re.Pattern)

    def test_custom_pattern_compiled_stored_as_is(self):
        pat = re.compile(r'^FME_\d{4}_Bid(\d+)_([A-Z]{2,4})\.xlsx$', re.IGNORECASE)
        r = XlsxBidReader(BIDS_1_DIR, filename_pattern=pat)
        assert r.filename_pattern is pat

    def test_custom_headers(self):
        hdrs = ("Order", "Price", "ID", "Name", "Team", "Pos", "Extra")
        r = XlsxBidReader(BIDS_1_DIR, expected_headers=hdrs)
        assert r.expected_headers == hdrs

    def test_string_directory_is_resolved_to_path(self):
        r = XlsxBidReader(str(BIDS_1_DIR))
        assert isinstance(r.directory, Path)


# ---------------------------------------------------------------------------
# _parse_filename (uses instance pattern)
# ---------------------------------------------------------------------------

class TestParseFilename:
    def test_valid_filename(self):
        code, rnd = _reader()._parse_filename("FME_2024_Bid1_ENG.xlsx")
        assert code == "ENG"
        assert rnd == 1

    def test_case_insensitive(self):
        code, rnd = _reader()._parse_filename("fme_2024_bid2_ger.xlsx")
        assert code == "GER"
        assert rnd == 2

    def test_invalid_raises(self):
        with pytest.raises(XlsxBidParseError, match="does not match"):
            _reader()._parse_filename("random_file.xlsx")


# ---------------------------------------------------------------------------
# read_file — uses configured directory, accepts bare filename
# ---------------------------------------------------------------------------

class TestReadFile:
    def test_eng_metadata(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        assert sub.manager_code == "ENG"
        assert sub.round_index == 1
        assert sub.source_file == "FME_2024_Bid1_ENG.xlsx"

    def test_eng_bids_non_empty(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        assert len(sub.rows) > 0

    def test_eng_known_bid(self):
        """ENG: Kane (id=257) at 251m, rank 1 (F)."""
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        kane = next((r for r in sub.rows if r.player_id == 257), None)
        assert kane is not None, "Kane bid not found"
        assert kane.amount == 251
        assert kane.rank_in_position == 1
        assert kane.player_name == "Kane"
        assert kane.position_str == "F"

    def test_all_rows_have_nonzero_rank(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        assert all(r.rank_in_position != 0 for r in sub.rows)

    def test_ger_known_bid(self):
        """GER: Havertz (id=7) at 120m, rank 4 (M)."""
        sub = _reader().read_file("FME_2024_Bid1_GER.xlsx")
        havertz = next((r for r in sub.rows if r.player_id == 7), None)
        assert havertz is not None
        assert havertz.amount == 120
        assert havertz.rank_in_position == 4

    def test_svk_empty_submission(self):
        """SVK submitted no bids — rows list should be empty."""
        sub = _reader().read_file("FME_2024_Bid1_SVK.xlsx")
        assert sub.rows == []

    def test_alb_bid_count(self):
        """ALB has 16 bids in round 1 (verified from 1轮暗标公示.txt)."""
        sub = _reader().read_file("FME_2024_Bid1_ALB.xlsx")
        assert len(sub.rows) == 16

    def test_unknown_filename_raises(self):
        with pytest.raises(XlsxBidParseError):
            _reader().read_file("NotAValidName.xlsx")


# ---------------------------------------------------------------------------
# to_raw_bids
# ---------------------------------------------------------------------------

class TestToRawBids:
    def test_binds_manager_id(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        raw = sub.to_raw_bids(manager_id=42)
        assert all(b.manager_id == 42 for b in raw)

    def test_returns_raw_bid_instances(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        raw = sub.to_raw_bids(manager_id=1)
        assert all(isinstance(b, RawBid) for b in raw)

    def test_length_matches_rows(self):
        sub = _reader().read_file("FME_2024_Bid1_GER.xlsx")
        raw = sub.to_raw_bids(manager_id=7)
        assert len(raw) == len(sub.rows)

    def test_fields_preserved(self):
        sub = _reader().read_file("FME_2024_Bid1_ENG.xlsx")
        raw = sub.to_raw_bids(manager_id=5)
        kane_raw = next((b for b in raw if b.player_id == 257), None)
        assert kane_raw is not None
        assert kane_raw.amount == 251
        assert kane_raw.rank_in_position == 1


# ---------------------------------------------------------------------------
# read_all — uses configured directory, no arguments
# ---------------------------------------------------------------------------

class TestReadAll:
    def test_reads_all_files(self):
        codes = {s.manager_code for s in _reader().read_all()}
        assert {"ENG", "GER", "ALB"}.issubset(codes)

    def test_sorted_by_manager_code(self):
        codes = [s.manager_code for s in _reader().read_all()]
        assert codes == sorted(codes)

    def test_all_round_index_1(self):
        assert all(s.round_index == 1 for s in _reader().read_all())

    def test_count_matches_files(self):
        n_files = sum(1 for _ in BIDS_1_DIR.glob("*.xlsx"))
        assert len(_reader().read_all()) == n_files

    def test_custom_pattern_filters_results(self):
        """A pattern that matches only ENG should return exactly one file."""
        pat = re.compile(r'^FME_\d{4}_Bid(\d+)_(ENG)\.xlsx$', re.IGNORECASE)
        r = XlsxBidReader(BIDS_1_DIR, filename_pattern=pat)
        subs = r.read_all()
        assert len(subs) == 1
        assert subs[0].manager_code == "ENG"
