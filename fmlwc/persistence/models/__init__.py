"""ORM model package.

Money convention: every monetary column in this package is stored as
an integer count of **millions of euros** (per FMLWC unit convention).



Models are split per aggregate so each file stays browsable. This
__init__ re-exports everything so callers can still do
`from fmlwc.persistence.models import Manager`.
"""

from .auction import AuctionResult, AuctionRound, Bid, Submission
from .eligibility import EligibilityRecord
from .injury import InjuryAdjustment
from .knockout import Pick, RosterSnapshot
from .match import (
    BonusAward,
    Fixture,
    Gameweek,
    Lineup,
    MatchResult,
    RealMatchEvent,
)
from .people import Manager, Player, RosterEntry
from .transfer import FreeSign, Release, Trade, TradeLeg, TransferWindow

__all__ = [
    # people
    "Manager", "Player", "RosterEntry",
    # auction
    "AuctionRound", "Submission", "Bid", "AuctionResult",
    # transfer
    "TransferWindow", "FreeSign", "Trade", "TradeLeg", "Release",
    # eligibility
    "EligibilityRecord",
    # match
    "Gameweek", "Fixture", "Lineup", "RealMatchEvent", "MatchResult", "BonusAward",
    # knockout
    "RosterSnapshot", "Pick",
    # injury
    "InjuryAdjustment",
]
