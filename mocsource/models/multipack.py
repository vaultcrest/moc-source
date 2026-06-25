from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Multipack(Base):
    __tablename__ = "multipacks"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    definition_source: Mapped[str | None] = mapped_column(Text)

    components: Mapped[list[MultipackComponent]] = relationship(back_populates="parent", cascade="all, delete-orphan")


class MultipackComponent(Base):
    __tablename__ = "multipack_components"

    parent_part_no: Mapped[str] = mapped_column(String(100), ForeignKey("multipacks.part_no", ondelete="CASCADE"), primary_key=True)
    child_part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    color_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_item_type: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[int | None] = mapped_column(Integer)

    parent: Mapped[Multipack] = relationship(back_populates="components")
