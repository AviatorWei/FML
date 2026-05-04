"""Domain exceptions.

One root + topical subclasses so callers can choose the granularity
they catch. All carry a free-form `reason` to surface in user feedback.
"""

from __future__ import annotations


class FmlwcError(Exception):
    """Base class for all engine errors."""


class ConfigError(FmlwcError):
    """Invalid or missing rule configuration."""


class EligibilityError(FmlwcError):
    """A signing was blocked by the eligibility gate."""


class AuctionError(FmlwcError):
    """Anything wrong during bid validation, cascade, or resolution."""


class TransferError(FmlwcError):
    """Free-sign / trade / release failed."""


class LineupError(FmlwcError):
    """Lineup violates position or count rules."""


class MatchError(FmlwcError):
    """Scoring, scheduling or knockout resolution problem."""


class StateError(FmlwcError):
    """Action attempted in the wrong season phase."""
