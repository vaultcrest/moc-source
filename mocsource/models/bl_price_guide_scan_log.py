from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BLPriceGuideScanLog(Base):
    __tablename__ = "bl_price_guide_scan_log"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    color_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
