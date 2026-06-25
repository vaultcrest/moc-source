from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class LegoElement(Base):
    __tablename__ = "lego_elements"

    element_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    design_id: Mapped[str | None] = mapped_column(String(50), index=True)
    lego_name: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(20))  # pab, bap, oos
    price_cents: Mapped[int | None] = mapped_column(Integer)
    price_formatted: Mapped[str | None] = mapped_column(String(20))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    bricklink_mapping: Mapped[BricklinkMapping | None] = relationship(back_populates="element", uselist=False, cascade="all, delete-orphan")


from .bricklink_mapping import BricklinkMapping  # noqa: E402
