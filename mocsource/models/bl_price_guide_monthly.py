from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BLPriceGuideMonthly(Base):
    __tablename__ = "bl_price_guide_monthly"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    color_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region: Mapped[str] = mapped_column(String(30), primary_key=True)
    new_or_used: Mapped[str] = mapped_column(String(1), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    avg_price_cents: Mapped[int | None] = mapped_column(Integer)
    min_price_cents: Mapped[int | None] = mapped_column(Integer)
    max_price_cents: Mapped[int | None] = mapped_column(Integer)
    median_price_cents: Mapped[int | None] = mapped_column(Integer)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    raw_sample_count: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
