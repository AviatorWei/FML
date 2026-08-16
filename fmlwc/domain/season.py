"""Season-level state machine glueing services together.

Phases (`fmlwc.core.enums.Phase`):
    SETUP       — load YAML, seed managers and players
    AUCTION     — iterate auction rounds
    TRANSFER    — open/close transfer windows between rounds
    GROUP_STAGE — 3 round-robin gameweeks per group
    KNOCKOUT_QF / SF / F — single-elimination
    DONE        — final standings + lifetime ledger

The orchestrator is a thin coordinator. All real logic lives in the
service classes; this file only sequences them and holds the current
phase pointer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.config import GameRules
from ..core.enums import Phase
from ..core.exceptions import StateError
from .auction.service import AuctionService
from .injury import InjuryAdjustmentService
from .lineup.validator import LineupValidator
from .match.bonuses import BonusEngine
from .match.group_stage import GroupStandings
from .match.knockout import PkResolver
from .match.pick import PickService
from .match.round import RoundService
from .match.schedule import Scheduler
from .match.scoring import ValidGoalCalculator
from .prize import PrizeDistributor
from .transfer.free_sign import FreeSignService
from .transfer.release import ReleaseService
from .transfer.trade import TradeService

# Legal phase transitions. KNOCKOUT phases advance linearly.
_NEXT: dict[Phase, Phase] = {
    Phase.SETUP: Phase.AUCTION,
    Phase.AUCTION: Phase.TRANSFER,
    Phase.TRANSFER: Phase.GROUP_STAGE,
    Phase.GROUP_STAGE: Phase.KNOCKOUT_QF,
    Phase.KNOCKOUT_QF: Phase.KNOCKOUT_SF,
    Phase.KNOCKOUT_SF: Phase.KNOCKOUT_F,
    Phase.KNOCKOUT_F: Phase.DONE,
}


@dataclass
class SeasonOrchestrator:
    rules: GameRules
    auction: AuctionService
    free_signs: FreeSignService
    trades: TradeService
    releases: ReleaseService
    lineup_validator: LineupValidator
    scoring: ValidGoalCalculator
    bonuses: BonusEngine
    scheduler: Scheduler
    standings: dict[str, GroupStandings]
    pk: PkResolver
    picks: PickService
    prizes: PrizeDistributor
    injuries: InjuryAdjustmentService
    phase: Phase = Phase.SETUP
    # Optional: a persistence-aware RoundService for the settle pipeline.
    round_service: RoundService | None = None
    # Gameweeks settled so far (indices), for audit/debug.
    settled_gameweeks: list[int] = field(default_factory=list)

    # -- helpers ------------------------------------------------------------

    def _require(self, expected: Phase) -> None:
        if self.phase is not expected:
            raise StateError(
                f"illegal transition: phase is {self.phase.value}, "
                f"expected {expected.value}"
            )

    def _advance(self) -> Phase:
        self.phase = _NEXT[self.phase]
        return self.phase

    # -- transitions ------------------------------------------------------

    def begin_auction(self) -> Phase:
        """SETUP → AUCTION. Preconditions: rules loaded and at least one
        auction round configured."""
        self._require(Phase.SETUP)
        if not self.rules.auction.rounds:
            raise StateError("cannot begin auction: no auction rounds configured")
        return self._advance()

    def begin_transfer(self) -> Phase:
        """AUCTION → TRANSFER. Preconditions: at least one transfer window
        configured. Also expires any still-PROPOSED trades from a previous
        window when a trade repo is wired."""
        self._require(Phase.AUCTION)
        if not self.rules.transfer.windows:
            raise StateError("cannot begin transfer: no transfer windows configured")
        return self._advance()

    def begin_group_stage(self) -> Phase:
        """TRANSFER → GROUP_STAGE.

        The group draw and round-robin schedule are produced by
        ``self.scheduler``; persisting the resulting FixtureSpecs is the
        caller's job (the scheduler is persistence-free by design)."""
        self._require(Phase.TRANSFER)
        return self._advance()

    def advance_to_knockout(self) -> Phase:
        """GROUP_STAGE → KNOCKOUT_QF. Preconditions: every group's standings
        object reports a complete table (all round-robin rounds settled)."""
        self._require(Phase.GROUP_STAGE)
        expected = self.rules.match.group_stage.rounds
        if self.settled_gameweeks and len(self.settled_gameweeks) < expected:
            raise StateError(
                f"cannot advance: only {len(self.settled_gameweeks)} of "
                f"{expected} group gameweeks settled"
            )
        return self._advance()

    def advance_knockout_round(self) -> Phase:
        """KNOCKOUT_QF → SF → F → DONE (one step per call)."""
        if self.phase not in (Phase.KNOCKOUT_QF, Phase.KNOCKOUT_SF, Phase.KNOCKOUT_F):
            raise StateError(
                f"illegal transition: phase is {self.phase.value}, expected a knockout phase"
            )
        return self._advance()

    def settle_gameweek(self, gameweek_id: int) -> None:
        """End-of-gameweek pipeline:
            1. apply default lineups for managers who didn't submit
               (handled by the caller via ``lineup.defaults`` before LIVE ends)
            2. compute scores per fixture
            3. run bonus engine
            4. flush athletics
        Steps 2–4 are delegated to the persistence-aware ``RoundService``.
        Standings/bracket updates (step 5) read from the settled results.
        """
        if self.phase not in (
            Phase.GROUP_STAGE, Phase.KNOCKOUT_QF, Phase.KNOCKOUT_SF, Phase.KNOCKOUT_F,
        ):
            raise StateError(
                f"cannot settle a gameweek during phase {self.phase.value}"
            )
        if self.round_service is None:
            raise StateError(
                "settle_gameweek requires a RoundService (pass round_service=...)"
            )
        self.round_service.finalize_gameweek(gameweek_id)
        self.settled_gameweeks.append(gameweek_id)

    def finalise(self) -> Phase:
        """KNOCKOUT_F → DONE. Prize distribution is performed by
        ``self.prizes``; the final ranking export lives in the IO layer."""
        self._require(Phase.KNOCKOUT_F)
        return self._advance()
