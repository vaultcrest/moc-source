from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RebrickableMinifigInventoryItem(Base):
    __tablename__ = "rebrickable_minifig_inventory_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    minifig_no: Mapped[str] = mapped_column(
        String(100), ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), nullable=False
    )
    rb_part_num: Mapped[str] = mapped_column(Text, nullable=False)
    rb_color_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bl_color_id: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_version: Mapped[int] = mapped_column(Integer, nullable=False)
