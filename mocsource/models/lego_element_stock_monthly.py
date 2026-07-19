from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegoElementStockMonthly(Base):
    __tablename__ = "lego_element_stock_monthly"

    element_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True
    )
    region: Mapped[str] = mapped_column(String(10), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    to_in_stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    to_out_of_stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seen_in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seen_out_of_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
