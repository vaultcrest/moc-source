from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import LegoElement, StudioResolution
from ..schemas.parts import LocalePriceResult, PartDetail, PartSummary, StudioResolutionOut

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


@router.get("/pab/price/{part_no}/{color_id}", response_model=list[LocalePriceResult], tags=["pab"])
async def pab_price(
    part_no: str,
    color_id: int,
    locale: str = Query("en-us", description="BCP-47 locale code, e.g. en-us, de-de, en-gb"),
    db: AsyncSession = Depends(get_db),
):
    """Price lookup by BL part_no + color_id for the browser extension.

    Queries lego_element_prices for the requested locale so the extension can
    display region-correct pricing. Falls back to en-us if the locale has no data.
    """
    from ..models import BricklinkMapping, LegoElementPrice

    def price_stmt(loc: str):
        return (
            select(
                LegoElementPrice.element_id,
                LegoElement.design_id,
                LegoElement.lego_name,
                LegoElementPrice.locale,
                LegoElementPrice.channel,
                LegoElementPrice.price_cents,
                LegoElementPrice.price_formatted,
                LegoElementPrice.currency_code,
                LegoElementPrice.in_stock,
            )
            .join(BricklinkMapping, BricklinkMapping.element_id == LegoElementPrice.element_id)
            .join(LegoElement, LegoElement.element_id == LegoElementPrice.element_id)
            .where(BricklinkMapping.part_no == part_no, BricklinkMapping.color_id == color_id)
            .where(LegoElementPrice.locale == loc)
            .where(LegoElementPrice.channel.in_(["pab", "bap"]))
        )

    result = await db.execute(price_stmt(locale))
    rows = result.mappings().all()

    # Fall back to en-us if the requested locale returned nothing
    if not rows and locale != "en-us":
        result = await db.execute(price_stmt("en-us"))
        rows = result.mappings().all()

    return [LocalePriceResult(**dict(r)) for r in rows]
