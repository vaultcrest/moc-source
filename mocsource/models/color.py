from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Color(Base):
    __tablename__ = "colors"

    bl_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bl_name: Mapped[str] = mapped_column(Text, nullable=False)
    lego_id: Mapped[int | None] = mapped_column(Integer)
    lego_name: Mapped[str | None] = mapped_column(Text)
    hex: Mapped[str | None] = mapped_column(String(6))
    rebrickable_id: Mapped[int | None] = mapped_column(Integer)
    color_type: Mapped[str | None] = mapped_column(Text)
    rebrickable_year_from: Mapped[int | None] = mapped_column(Integer)
    rebrickable_year_to: Mapped[int | None] = mapped_column(Integer)
    bl_year_from: Mapped[int | None] = mapped_column(Integer)
    bl_year_to: Mapped[int | None] = mapped_column(Integer)
