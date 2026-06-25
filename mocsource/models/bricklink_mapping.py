from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class BricklinkMapping(Base):
    __tablename__ = "bricklink_mappings"

    element_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True)
    part_no: Mapped[str | None] = mapped_column(String(100), index=True)
    color_id: Mapped[int | None] = mapped_column(Integer)
    item_type: Mapped[str | None] = mapped_column(String(20))
    part_name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))  # bricklink, rebrickable
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    element: Mapped[LegoElement] = relationship(back_populates="bricklink_mapping")


from .lego_element import LegoElement  # noqa: E402
