from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegoElementPrice(Base):
    __tablename__ = "lego_element_prices"

    element_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)
    channel: Mapped[str | None] = mapped_column(String(20))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    price_formatted: Mapped[str | None] = mapped_column(String(20))
    currency_code: Mapped[str | None] = mapped_column(String(10))
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
