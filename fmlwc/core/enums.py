"""Engine-wide enumerations.

Every constant string used across modules lives here. Keeping the values
short and stable lets us serialise them safely into YAML / SQLite and
compare without typos.
"""

from __future__ import annotations

import enum


class Position(str, enum.Enum):
    """Real-world football position. Values match the rule shorthand."""

    G = "G"
    D = "D"
    M = "M"
    F = "F"

    @classmethod
    def order_high_to_low(cls) -> list["Position"]:
        """Ordering used by cascade tie-break: F > M > D > G."""
        return [cls.F, cls.M, cls.D, cls.G]

    def can_play_as(self, slot: "Position") -> bool:
        """Backward-substitution: a higher-numbered position can fill lower.

        D → M/F, M → F, others only their native slot.
        """
        if self is slot:
            return True
        if self is Position.D and slot in (Position.M, Position.F):
            return True
        if self is Position.M and slot is Position.F:
            return True
        return False


class Phase(str, enum.Enum):
    """Top-level season phase used by the orchestrator state machine."""

    SETUP = "SETUP"
    AUCTION = "AUCTION"
    TRANSFER = "TRANSFER"
    GROUP_STAGE = "GROUP_STAGE"
    KNOCKOUT_QF = "KNOCKOUT_QF"
    KNOCKOUT_SF = "KNOCKOUT_SF"
    KNOCKOUT_F = "KNOCKOUT_F"
    DONE = "DONE"


class AuctionRoundStatus(str, enum.Enum):
    OPEN = "OPEN"
    RESOLVING = "RESOLVING"
    CLOSED = "CLOSED"


class BidStatus(str, enum.Enum):
    """Bid lifecycle. Cascade may invalidate; resolution awards or loses."""

    SUBMITTED = "SUBMITTED"
    VALID = "VALID"
    INVALID_PER_BID = "INVALID_PER_BID"          # rule 二.3
    INVALID_POS_CAP = "INVALID_POS_CAP"          # rule 二.4
    INVALID_BUDGET = "INVALID_BUDGET"            # rule 二.5
    INVALID_INELIGIBLE = "INVALID_INELIGIBLE"    # rule 二.3.(4)
    AWARDED = "AWARDED"
    LOST = "LOST"


class TransferWindowStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TradeStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TradeSide(str, enum.Enum):
    INITIATOR = "INITIATOR"
    COUNTERPARTY = "COUNTERPARTY"


class AcquisitionVia(str, enum.Enum):
    AUCTION = "AUCTION"
    FREE_SIGN = "FREE_SIGN"
    TRADE = "TRADE"
    KO_PICK = "KO_PICK"
    INJURY_GRANT = "INJURY_GRANT"


class EligibilityRestriction(str, enum.Enum):
    AUCTION_OTHERS_NEXT_WINDOW = "AUCTION_OTHERS_NEXT_WINDOW"
    FREE_SIGN_SAME_WINDOW = "FREE_SIGN_SAME_WINDOW"
    RELEASED_LIFETIME = "RELEASED_LIFETIME"
    DISMISSED_LIFETIME = "DISMISSED_LIFETIME"
    KNOCKOUT_PICK_BLACKLIST = "KNOCKOUT_PICK_BLACKLIST"


class RealEventType(str, enum.Enum):
    """Normalised real-match events used as scoring input."""

    GOAL = "GOAL"
    OWN_GOAL = "OWN_GOAL"
    SAVED_PENALTY_BY_GK = "SAVED_PENALTY_BY_GK"
    MISSED_PENALTY = "MISSED_PENALTY"
    ASSIST = "ASSIST"
    YELLOW = "YELLOW"
    SECOND_YELLOW_RED = "SECOND_YELLOW_RED"
    RED = "RED"


class MatchOutcome(str, enum.Enum):
    HOME_WIN = "HOME_WIN"
    AWAY_WIN = "AWAY_WIN"
    DRAW = "DRAW"


class GameweekPhase(str, enum.Enum):
    GROUP = "GROUP"
    QF = "QF"
    SF = "SF"
    F = "F"


class GameweekStatus(str, enum.Enum):
    PENDING = "PENDING"
    LIVE = "LIVE"
    FINALIZED = "FINALIZED"
