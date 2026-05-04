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

from dataclasses import dataclass

from ..core.config import GameRules
from ..core.enums import Phase
from .auction import AuctionService
from .injury import InjuryAdjustmentService
from .lineup import LineupValidator
from .match import (
    BonusEngine,
    ValidGoalCalculator,
    GroupStandings,
    PickService,
    PkResolver,
    Scheduler,
)
from .prize import PrizeDistributor
from .transfer import FreeSignService, ReleaseService, TradeService


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

    # -- transitions ------------------------------------------------------
    def begin_auction(self) -> None:
        raise NotImplementedError("TODO: SETUP → AUCTION precondition checks")

    def begin_transfer(self) -> None:
        raise NotImplementedError("TODO: AUCTION → TRANSFER")

    def begin_group_stage(self) -> None:
        raise NotImplementedError(
            "TODO: TRANSFER → GROUP_STAGE; draw groups; build round-robin schedule"
        )

    def advance_to_knockout(self) -> None:
        raise NotImplementedError(
            "TODO: collect group standings, build bracket, seed eligibility records, "
            "transition GROUP_STAGE → KNOCKOUT_QF"
        )

    def settle_gameweek(self, gameweek_id: int) -> None:
        """End-of-gameweek pipeline:
            1. apply default lineups for managers who didn't submit
            2. compute scores per fixture
            3. run bonus engine
            4. update standings (group) or bracket (knockout)
            5. take roster snapshots if knockout
        """
        raise NotImplementedError("TODO")

    def finalise(self) -> None:
        raise NotImplementedError("TODO: DONE; emit final ranking JSO