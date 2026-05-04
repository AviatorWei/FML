"""Placeholder. Once services are implemented, prioritise tests for:

- auction.cascade.CascadeInvalidator
    * position-cap loop respects F>M>D>G drop order
    * budget loop drops highest first, applying same tiebreak
- auction.tiebreaker.AmountRankTimeDraw
    * exhaustive 4-key ordering
- lineup.validator.LineupValidator
    * backward substitution (D->M/F, M->F)
    * misplaced player silently dropped
    * appearance caps + must_have GK
- match.knockout.PkResolver
    * top-5 sum, then position-by-position
    * one side empty -> other wins
- prizes.PrizeDistributor
    * weights sum to pool (round_half_up consistency)
"""

def test_smoke() -> None:
    import fmlwc

    assert fmlwc.__version__
