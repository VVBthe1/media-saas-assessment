"""SQLAlchemy models; import concrete tables from their modules (e.g. backend.models.tenant)."""

from backend.models.base import Base

__all__ = ["Base"]
