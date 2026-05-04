"""FMLWC — Fantasy Major-tournament League With Cash.

A rule-configurable fantasy football engine aligned with FME-2021 (Euro
2020/2021) rules. See `RULES.md` for canonical rule text and `DESIGN.md`
for the architectural overview.

Layout
------
    core         — shared kernel: enums, exceptions, configuration
    persistence  — storage: SQLAlchemy engine, ORM models, repositories
    domain       — business services, organised by bounded context

Public sub-packages are intentionally NOT eagerly imported here so
importing `fmlwc` doesn't pull in SQLAlchemy or YAML. Import what you
need: `from fmlwc.domain.auction import AuctionService`.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
