from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LegoSetInventoryItem(Base):
    __tablename__ = "lego_set_inventory_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(30), ForeignKey("lego_sets.set_num", ondelete="CASCADE"), nullable=False)
    rb_part_num: Mapped[str] = mapped_column(Text, nullable=False)
    rb_color_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bl_color_id: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_spare: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inventory_version: Mapped[int] = mapped_column(Integer, nullable=False)
