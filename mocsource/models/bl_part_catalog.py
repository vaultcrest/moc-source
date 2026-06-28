from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BLPartCatalog(Base):
    __tablename__ = "bl_part_catalog"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    item_type: Mapped[str | None] = mapped_column(String(20))
    looked_up_at: Mapped[datetime | None] = mapped_column(DateTime)
