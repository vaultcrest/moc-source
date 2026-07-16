from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BricklinkAlternate(Base):
    __tablename__ = "bricklink_alternates"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    alternate_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str | None] = mapped_column(String(50))  # bl_alternate_no, brickstore_alternate_ids, brickstore_mold_group
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
