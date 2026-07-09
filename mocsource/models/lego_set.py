from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegoSet(Base):
    __tablename__ = "lego_sets"

    set_num: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    theme_id: Mapped[int | None] = mapped_column(Integer)
    num_parts: Mapped[int | None] = mapped_column(Integer)
    img_url: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
