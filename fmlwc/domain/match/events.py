"""Real-match event normalisation.

External feeds (UEFA, Whoscored, hand-entered) come in many shapes. We
normalise them into `RealMatchEvent` rows whose schema is fixed
(`fmlwc.core.enums.RealEventType`). Once events are in the DB, scoring,
bonuses, and PK calculations all read from the same canonical stream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...core.enums import RealEventType


@dataclass(frozen=True)
class NormalisedEvent:
    gameweek_id: int
    real_match_id: str
    real_player_id: int
    event_type: RealEventType
    value: float = 1.0
    minute: int | None = None
    is_extra_time: bool = False
    is_shootout: bool = False


class EventImporter(ABC):
    """Adapter base class for an external feed."""

    @abstractmethod
    def import_for(self, gameweek_id: int) -> list[NormalisedEvent]: ...


class ManualImporter(EventImporter):
    """Test/demo helper: events handed in directly."""

    def __init__(self, events: list[NormalisedEvent]) -> None:
        self._events = events

    def import_for(self, gameweek_id: int) -> list[NormalisedEvent]:
        return [e for e in self._events if e.gameweek_id == gameweek_id]
