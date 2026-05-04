"""Sealed-bid auction package.

Submodules:
    bids        - per-bid validation and value objects
    cascade     - position-cap and budget cascade invalidation
    tiebreaker  - per-player winner selection
    service     - orchestrates one round end-to-end (DB-backed)

Note: nothing is re-exported here, to keep algorithmic submodules
importable without pulling in SQLAlchemy via service. Import directly:

    from fmlwc.domain.auction.cascade import CascadeInvalidator
    from fmlwc.domain.auction.service import AuctionService
"""
