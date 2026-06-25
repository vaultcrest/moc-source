from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import LegoElement, StudioResolution
from ..schemas.parts import PartDetail, PartSummary, StudioResolutionOut

router = APIRouter(prefix="/api/v1/parts", tags=["parts"])


@router.get("/", response_model=list[PartSummary])
async def list_parts(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    channel: str | None = Query(None, description="Filter by channel: pab, bap, oos"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LegoElement).offset(offset).limit(limit)
    if channel:
        stmt = stmt.where(LegoElement.channel == channel)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{element_id}", response_model=PartDetail)
async def get_part(element_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(LegoElement).where(LegoElement.element_id == element_id).options(selectinload(LegoElement.bricklink_mapping))
    result = await db.execute(stmt)
    element = result.scalar_one_or_none()
    if element is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return element


@router.get("/pab/price/{part_no}/{color_id}", response_model=list[PartSummary], tags=["pab"])
async def pab_price(part_no: str, color_id: int, db: AsyncSession = Depends(get_db)):
    """Price lookup by BL part_no + color_id — for the browser extension."""
    from ..models import BricklinkMapping

    stmt = (
        select(LegoElement)
        .join(BricklinkMapping, BricklinkMapping.element_id == LegoElement.element_id)
        .where(BricklinkMapping.part_no == part_no, BricklinkMapping.color_id == color_id)
        .where(LegoElement.channel.in_(["pab", "bap"]))
    )
    result = await db.execute(stmt)
    return result.scalars().all()
