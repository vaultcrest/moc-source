from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MinifigMapping(Base):
    __tablename__ = "minifig_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fig_num: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    minifig_no: Mapped[str] = mapped_column(
        String(100), ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    matched_via_set_num: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
