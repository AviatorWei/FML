"""Single declarative base for every ORM model in the project.

Lives in its own module so model files can `from ..base import Base`
without cyclic imports back into `db.py`.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy 2.0 declarative base."""
