"""Public auction announcement formatter (暗标公示).

Converts a list of ``BidAnnouncementRow`` objects — produced by
``AuctionService.announcement_views()`` — into the plain-text format used
in the FME public disclosure.

Format per line (modelled on the historical example files)::

    {rank:<1}   {amount_m:<5}{name:<20}{pos}  {team:<3}         {player_id}号  {manager}

Players are separated by a blank line.  Within each player group, bids are
sorted by amount descending (highest first).

Typical usage::

    views = service.announcement_views(round_id)
    text = AuctionAnnouncementFormatter().format(views)
    Path("暗标公示.txt").write_text(text, encoding="utf-8")
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from ..domain.auction.service import BidAnnouncementRow


@dataclass
class AuctionAnnouncementFormatter:
    """Stateless formatter; create once and call ``format()`` as needed."""

    def format(self, rows: list[BidAnnouncementRow]) -> str:
        """Return the full announcement as a UTF-8 string.

        Parameters
        ----------
        rows:
            Output of ``AuctionService.announcement_views()``.  Already
            sorted by (player_id asc, amount desc); the formatter respects
            that order.
        """
        if not rows:
            return ""

        blocks: list[str] = []

        # Group by player_id (rows are pre-sorted by player_id)
        for _pid, group in groupby(rows, key=lambda r: r.player_id):
            player_lines = [self._format_line(r) for r in group]
            blocks.append("\n".join(player_lines))

        return "\n\n".join(blocks) + "\n"

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _format_line(r: BidAnnouncementRow) -> str:
        amount_m = f"{r.amount}m".ljust(5)   # e.g. "10m  " / "131m "
        name = r.player_name.ljust(20)        # left-pad to 20 chars
        return (
            f"{r.rank_in_position:<1}"
            f"   "
            f"{amount_m}"
            f"{name}"
            f"{r.position:<1}"
            f"  "
            f"{r.real_team:<3}"
            f"         "
            f"{r.player_id}号"
            f"  "
            f"{r.manager_code}"
        )
