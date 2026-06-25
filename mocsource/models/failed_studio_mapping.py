from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FailedStudioMapping(Base):
    __tablename__ = "failed_studio_mappings"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    color_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    bricklink_name: Mapped[str | None] = mapped_column(Text)
    lego_name: Mapped[str | None] = mapped_column(Text)
