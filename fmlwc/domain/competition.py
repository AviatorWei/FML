"""Dual-competition (league + cup) player eligibility.

Implements the FML↔FMC relationship (fml-fmc-rules.md 第七十七条/第七十八条):

1. Managers sign two kinds of players:
     * **league players** — real team is part of the league pool; they are
       the FML roster (阵容).
     * **cup-exclusive players** — real team is one of ``cup.extra_teams``
       (teams only in the cup); they belong only to the cup list (FMC大名单).
2. During the cup **group stage** the rosters are LINKED: every owned player
   whose real team plays the cup is implicitly in the cup list, so a dual
   player (``cup.league_teams_in_cup``) may start in BOTH league and cup
   lineups, and sign/release/trade operations act on both games at once.
3. Once the cup enters its **knockout stage** the games SEPARATE
   (第七十七条: "FML将与FMC独立"): the cup list is forked into its own
   table; afterwards each operation targets exactly one game. A dual player
   may remain in both rosters — and keep starting in both competitions —
   but releasing/trading them in one game no longer affects the other.
4. Funds (第七十八条): the cup wallet may only pay for cup-exclusive
   players during the group stage; after separation the restriction lifts.

This module holds the pure rules; persistence (the fork itself, roster
lookups) lives in the web/DB layer, which passes state in.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import GameRules
from ..core.enums import Competition


@dataclass(frozen=True)
class CompetitionVerdict:
    allowed: bool
    reason: str | None = None

    @classmethod
    def ok(cls) -> "CompetitionVerdict":
        return cls(True, None)

    @classmethod
    def deny(cls, reason: str) -> "CompetitionVerdict":
        return cls(False, reason)


class CupEligibilityService:
    def __init__(self, rules: GameRules) -> None:
        self.rules = rules

    # -- team classification ---------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.rules.cup.enabled

    def is_cup_only_team(self, real_team: str) -> bool:
        """Extra teams exist only in the cup; their players never play league."""
        return real_team in self.rules.cup.extra_teams

    def is_dual_team(self, real_team: str) -> bool:
        """League real teams that also qualified for the cup."""
        return real_team in self.rules.cup.league_teams_in_cup

    def is_cup_team(self, real_team: str) -> bool:
        return self.is_cup_only_team(real_team) or self.is_dual_team(real_team)

    def classify(self, real_team: str) -> str:
        """'CUP_ONLY' | 'DUAL' | 'LEAGUE_ONLY' — for UI badges/exports."""
        if self.is_cup_only_team(real_team):
            return "CUP_ONLY"
        if self.is_dual_team(real_team):
            return "DUAL"
        return "LEAGUE_ONLY"

    # -- lineup eligibility ---------------------------------------------------

    def check_starter(
        self,
        real_team: str,
        competition: Competition,
        *,
        separated: bool,
        on_cup_roster: bool = True,
    ) -> CompetitionVerdict:
        """May a player from *real_team* start in a *competition* lineup?

        Parameters
        ----------
        separated:
            True once the cup fork has happened (knockout stage).
        on_cup_roster:
            After separation, whether this player is on the manager's forked
            cup list. Ignored before separation (the cup list is implicit).
        """
        if not self.enabled:
            return CompetitionVerdict.ok()

        kind = self.classify(real_team)

        if competition is Competition.LEAGUE:
            # League lineups always come from the league roster; cup-only
            # players are never league-eligible (第十条: FML阵容仅含联赛球员).
            if kind == "CUP_ONLY":
                return CompetitionVerdict.deny(
                    f"{real_team} is a cup-only team — its players cannot "
                    "start in league lineups")
            return CompetitionVerdict.ok()

        # competition is CUP
        if kind == "LEAGUE_ONLY":
            return CompetitionVerdict.deny(
                f"{real_team} is not in the cup — its players cannot start "
                "in cup lineups")
        if separated and not on_cup_roster:
            return CompetitionVerdict.deny(
                "after separation the cup list is independent — this player "
                "is not on the manager's cup roster")
        return CompetitionVerdict.ok()

    # -- separation ----------------------------------------------------------------

    def separation_due(self, cup_knockout_started: bool) -> bool:
        """The fork should happen once the first cup knockout gameweek starts
        (第七十七条: 淘汰赛阶段 FML 与 FMC 独立), if enabled in config."""
        if not self.enabled or not self.rules.cup.separate_after_group:
            return False
        return cup_knockout_started

    # -- funds (第七十八条) -----------------------------------------------------------

    def check_cup_spend(
        self, real_team: str, *, separated: bool
    ) -> CompetitionVerdict:
        """May the cup wallet pay for a player from *real_team*?

        Group stage: cup funds only for cup-exclusive players.
        After separation: unrestricted.
        """
        if not self.enabled:
            return CompetitionVerdict.deny("cup mode is disabled")
        if separated:
            return CompetitionVerdict.ok()
        if not self.is_cup_only_team(real_team):
            return CompetitionVerdict.deny(
                "during the cup group stage, cup funds may only sign "
                "players from cup-exclusive teams (第七十八条)")
        return CompetitionVerdict.ok()
