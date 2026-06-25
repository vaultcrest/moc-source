from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StudioResolution(Base):
    """Resolution of a BrickLink part_no to its Studio/LDraw .dat file.

    Keyed by part_no (not element_id) because the Studio file is a property
    of the part geometry, shared across all elements of that part.
    """

    __tablename__ = "studio_resolutions"

    part_no: Mapped[str] = mapped_column(String(100), primary_key=True)
    part_file: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(50))
    resolution_method: Mapped[str | None] = mapped_column(String(50))  # exact, alias, print_revision, geometry_revision, alternate
    resolved_from: Mapped[str | None] = mapped_column(String(100))
    studio_color_id: Mapped[int | None] = mapped_column(Integer)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
