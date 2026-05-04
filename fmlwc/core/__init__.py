"""Shared kernel — enums, exceptions, configuration loader.

Anything that has no dependency on storage or domain logic lives here.
This package is safe to import from any other layer.
"""

from .config import GameRules
from .exceptions import (
    AuctionError,
    ConfigError,
    EligibilityError,
    FmlwcError,
    LineupError,
    MatchError,
    StateError,
    TransferError,
)

__all__ = [
    "GameRules",
    "FmlwcError",
    "ConfigError",
    "EligibilityError",
    "AuctionError",
    "TransferError",
    "LineupError",
    "MatchError",
    "StateError",
]
