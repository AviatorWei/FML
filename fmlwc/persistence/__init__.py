"""Persistence layer.

Nothing eagerly imported so pure-algorithmic domain modules can run
without SQLAlchemy. Import explicitly:

    from fmlwc.persistence.base import Base
    from fmlwc.persistence.db import make_engine, session_scope
    from fmlwc.persistence.models import Manager, Bid, Fixture
    from fmlwc.persistence.repositories import SqlManagerRepo
"""
