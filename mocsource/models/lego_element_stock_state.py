from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegoElementStockState(Base):
    __tablename__ = "lego_element_stock_state"

    element_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True
    )
    region: Mapped[str] = mapped_column(String(10), primary_key=True)
    currently_in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_seen_in_stock_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
