"""Domain layer — business services organised by bounded context.

Sub-packages (multiple files):
    auction   — sealed-bid auction (bids, cascade, tiebreaker, service)
    transfer  — transfer window operations (free sign, trade, release)
    lineup    — lineup validation + default-fill strategies
    match     — events, scoring, bonuses, schedule, knockout, pick

Single-file modules:
    eligibility — anti-collusion / lifetime / cooldown signing gate
    prize       — qualifier and advancement prizes
    injury      — real-squad injury exception handling
    season      — top-level state-machine orchestrator
"""

__all__: list[str] = []
