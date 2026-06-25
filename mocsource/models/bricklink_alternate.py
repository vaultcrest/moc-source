from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BricklinkAlternate(Base):
    __tablename__ = "bricklink_alternates"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    alternate_no: Mapped[str] = mapped_column(String(100), primary_key=True)
