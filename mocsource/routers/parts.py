from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select, text
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
    response: Response,
    locale: str = Query("en-us", description="BCP-47 locale code, e.g. en-us, de-de, en-gb"),
    db: AsyncSession = Depends(get_db),
):
    """Price lookup by BL part_no + color_id for the browser extension.

    Queries lego_element_prices for the requested locale so the extension can
    display region-correct pricing. Falls back to en-us if the locale has no data.
    """
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=60"
    from ..models import BricklinkMapping, Color, LegoElementPrice

    def price_stmt(loc: str):
        return (
            select(
                LegoElementPrice.element_id,
                LegoElement.design_id,
                LegoElement.lego_name,
                BricklinkMapping.part_name.label("bl_part_name"),
                BricklinkMapping.color_id.label("bl_color_id"),
                Color.bl_name.label("bl_color_name"),
                Color.hex.label("bl_color_hex"),
                Color.lego_id.label("lego_color_id"),
                Color.lego_name.label("lego_color_name"),
                LegoElementPrice.locale,
                LegoElementPrice.channel,
                LegoElementPrice.price_cents,
                LegoElementPrice.price_formatted,
                LegoElementPrice.currency_code,
                LegoElementPrice.in_stock,
            )
            .join(BricklinkMapping, BricklinkMapping.element_id == LegoElementPrice.element_id)
            .join(LegoElement, LegoElement.element_id == LegoElementPrice.element_id)
            .outerjoin(Color, Color.bl_id == BricklinkMapping.color_id)
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

    if rows:
        return [LocalePriceResult(**dict(r)) for r in rows]

    # No PAB/BAP price — return part info only so the extension still has the name
    info_stmt = (
        select(
            BricklinkMapping.element_id,
            LegoElement.design_id,
            LegoElement.lego_name,
            BricklinkMapping.part_no.label("bl_part_no"),
            BricklinkMapping.part_name.label("bl_part_name"),
            BricklinkMapping.color_id.label("bl_color_id"),
            Color.bl_name.label("bl_color_name"),
            Color.hex.label("bl_color_hex"),
            Color.lego_id.label("lego_color_id"),
            Color.lego_name.label("lego_color_name"),
        )
        .join(LegoElement, LegoElement.element_id == BricklinkMapping.element_id)
        .outerjoin(Color, Color.bl_id == BricklinkMapping.color_id)
        .where(BricklinkMapping.part_no == part_no, BricklinkMapping.color_id == color_id)
        .limit(1)
    )
    info_result = await db.execute(info_stmt)
    info_row = info_result.mappings().first()
    if not info_row:
        # Part+color combo not in our DB — try BL catalog for the name, colors table for the color
        from datetime import datetime

        from ..bl_client import fetch_bl_part
        from ..models import BLPartCatalog

        cached = await db.execute(select(BLPartCatalog).where(BLPartCatalog.part_no == part_no))
        cached_row = cached.scalar_one_or_none()
        part_name = cached_row.name if cached_row else None

        if part_name is None:
            bl_data = await fetch_bl_part(part_no)
            if bl_data:
                part_name = bl_data.get("name")
                now = datetime.utcnow()
                if cached_row:
                    cached_row.name = part_name
                    cached_row.item_type = bl_data.get("item_type")
                    cached_row.looked_up_at = now
                else:
                    db.add(BLPartCatalog(
                        part_no=part_no,
                        name=part_name,
                        item_type=bl_data.get("item_type"),
                        looked_up_at=now,
                    ))
                await db.commit()

        color_result = await db.execute(select(Color).where(Color.bl_id == color_id))
        color_row = color_result.scalar_one_or_none()

        if not part_name and not color_row:
            return []

        # Rebrickable enrichment for BL part+color lookups is disabled — it ran once per
        # unmapped part a user happened to browse, which was far too much volume for
        # Rebrickable's rate limit and got this server IP-banned. New elements are now
        # resolved once, at scrape time, in scripts/scrape_pab.py instead.

        return [LocalePriceResult(
            bl_part_no=part_no,
            bl_part_name=part_name,
            bl_color_id=color_id,
            bl_color_name=color_row.bl_name if color_row else None,
            bl_color_hex=color_row.hex if color_row else None,
            locale=locale,
            channel=None,
            price_cents=None,
            price_formatted=None,
            currency_code=None,
            in_stock=None,
        )]

    # Prefer the canonical BrickLink name (source != 'rebrickable') for this part_no
    # so we show "Wedge 2 x 2 x 2/3 Right" not "Slope Curved 2 x 2 with Stud Notch Right"
    from sqlalchemy import or_
    canonical_name_stmt = (
        select(BricklinkMapping.part_name)
        .where(BricklinkMapping.part_no == part_no)
        .where(or_(BricklinkMapping.source.is_(None), BricklinkMapping.source != "rebrickable"))
        .limit(1)
    )
    canonical_result = await db.execute(canonical_name_stmt)
    canonical_name = canonical_result.scalar_one_or_none()

    return [LocalePriceResult(
        element_id=info_row["element_id"],
        design_id=info_row["design_id"],
        lego_name=info_row["lego_name"],
        bl_part_no=info_row["bl_part_no"],
        bl_part_name=canonical_name or info_row["bl_part_name"],
        bl_color_id=info_row["bl_color_id"],
        bl_color_name=info_row["bl_color_name"],
        bl_color_hex=info_row["bl_color_hex"],
        lego_color_id=info_row["lego_color_id"],
        lego_color_name=info_row["lego_color_name"],
        locale=locale,
        channel=None,
        price_cents=None,
        price_formatted=None,
        currency_code=None,
        in_stock=None,
    )]


@router.get("/pab/prices/{part_no}", response_model=list[LocalePriceResult], tags=["pab"])
async def pab_all_prices_for_part(
    part_no: str,
    response: Response,
    locale: str = Query("en-us"),
    db: AsyncSession = Depends(get_db),
):
    """All in-stock PAB color/price combinations for a part number. Used by catalog page injection."""
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=60"
    from ..models import BricklinkMapping, Color, LegoElementPrice
    from sqlalchemy import desc

    def stmt(loc: str):
        return (
            select(
                LegoElementPrice.element_id,
                LegoElement.design_id,
                LegoElement.lego_name,
                BricklinkMapping.part_no.label("bl_part_no"),
                BricklinkMapping.part_name.label("bl_part_name"),
                BricklinkMapping.color_id.label("bl_color_id"),
                Color.bl_name.label("bl_color_name"),
                Color.hex.label("bl_color_hex"),
                Color.lego_id.label("lego_color_id"),
                Color.lego_name.label("lego_color_name"),
                LegoElementPrice.locale,
                LegoElementPrice.channel,
                LegoElementPrice.price_cents,
                LegoElementPrice.price_formatted,
                LegoElementPrice.currency_code,
                LegoElementPrice.in_stock,
            )
            .join(BricklinkMapping, BricklinkMapping.element_id == LegoElementPrice.element_id)
            .join(LegoElement, LegoElement.element_id == LegoElementPrice.element_id)
            .outerjoin(Color, Color.bl_id == BricklinkMapping.color_id)
            .where(BricklinkMapping.part_no == part_no)
            .where(LegoElementPrice.locale == loc)
            .where(LegoElementPrice.channel.in_(["pab", "bap"]))
            .where(LegoElementPrice.in_stock == True)
            .order_by(desc(LegoElementPrice.price_cents))
        )

    result = await db.execute(stmt(locale))
    rows = result.mappings().all()
    if not rows and locale != "en-us":
        result = await db.execute(stmt("en-us"))
        rows = result.mappings().all()
    return [LocalePriceResult(**dict(r)) for r in rows]


@router.get("/element/{element_id}/price", response_model=list[LocalePriceResult], tags=["pab"])
async def pab_price_by_element(
    element_id: int,
    response: Response,
    locale: str = Query("en-us"),
    db: AsyncSession = Depends(get_db),
):
    """Price + BL metadata lookup by LEGO element_id for LEGO cart items."""
    from ..models import BricklinkMapping, Color, LegoElementPrice

    def price_stmt(loc: str):
        return (
            select(
                LegoElementPrice.element_id,
                LegoElement.design_id,
                LegoElement.lego_name,
                BricklinkMapping.part_no.label("bl_part_no"),
                BricklinkMapping.part_name.label("bl_part_name"),
                BricklinkMapping.color_id.label("bl_color_id"),
                Color.bl_name.label("bl_color_name"),
                Color.hex.label("bl_color_hex"),
                Color.lego_id.label("lego_color_id"),
                Color.lego_name.label("lego_color_name"),
                LegoElementPrice.locale,
                LegoElementPrice.channel,
                LegoElementPrice.price_cents,
                LegoElementPrice.price_formatted,
                LegoElementPrice.currency_code,
                LegoElementPrice.in_stock,
            )
            .join(BricklinkMapping, BricklinkMapping.element_id == LegoElementPrice.element_id)
            .join(LegoElement, LegoElement.element_id == LegoElementPrice.element_id)
            .outerjoin(Color, Color.bl_id == BricklinkMapping.color_id)
            .where(LegoElementPrice.element_id == element_id)
            .where(LegoElementPrice.locale == loc)
            .where(LegoElementPrice.channel.in_(["pab", "bap"]))
        )

    result = await db.execute(price_stmt(locale))
    rows = result.mappings().all()
    if not rows and locale != "en-us":
        result = await db.execute(price_stmt("en-us"))
        rows = result.mappings().all()

    if rows:
        response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=60"
        return [LocalePriceResult(**dict(r)) for r in rows]

    # No price row — return mapping info only so extension has BL name/color
    info_stmt = (
        select(
            BricklinkMapping.element_id,
            LegoElement.design_id,
            LegoElement.lego_name,
            BricklinkMapping.part_no.label("bl_part_no"),
            BricklinkMapping.part_name.label("bl_part_name"),
            BricklinkMapping.color_id.label("bl_color_id"),
            Color.bl_name.label("bl_color_name"),
            Color.hex.label("bl_color_hex"),
            Color.lego_id.label("lego_color_id"),
            Color.lego_name.label("lego_color_name"),
        )
        .join(LegoElement, LegoElement.element_id == BricklinkMapping.element_id)
        .outerjoin(Color, Color.bl_id == BricklinkMapping.color_id)
        .where(BricklinkMapping.element_id == element_id)
        .limit(1)
    )
    info_result = await db.execute(info_stmt)
    info_row = info_result.mappings().first()
    if not info_row:
        # No BL mapping. Rebrickable enrichment here is disabled — new elements are
        # resolved once, at scrape time, in scripts/scrape_pab.py instead of per request.
        response.headers["Cache-Control"] = "no-store"
        return []

    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=60"
    return [LocalePriceResult(
        element_id=info_row["element_id"],
        design_id=info_row["design_id"],
        lego_name=info_row["lego_name"],
        bl_part_no=info_row["bl_part_no"],
        bl_part_name=info_row["bl_part_name"],
        bl_color_id=info_row["bl_color_id"],
        bl_color_name=info_row["bl_color_name"],
        bl_color_hex=info_row["bl_color_hex"],
        lego_color_id=info_row["lego_color_id"],
        lego_color_name=info_row["lego_color_name"],
        locale=locale,
        channel=None,
        price_cents=None,
        price_formatted=None,
        currency_code=None,
        in_stock=None,
    )]


class DataFreshness(BaseModel):
    stock_checked_at: Optional[datetime]
    prices_updated_at: Optional[datetime]


@router.get("/pab/freshness", response_model=DataFreshness, tags=["pab"])
async def pab_freshness(db: AsyncSession = Depends(get_db)):
    """When stock was last checked (hourly OOS run) and prices last updated (daily full run)."""
    result = await db.execute(text("""
        SELECT
            MAX(finished_at) FILTER (WHERE success = true)                   AS stock_checked_at,
            MAX(finished_at) FILTER (WHERE mode = 'full' AND success = true) AS prices_updated_at
        FROM scraper_runs
    """))
    row = result.mappings().one()
    return DataFreshness(
        stock_checked_at=row["stock_checked_at"],
        prices_updated_at=row["prices_updated_at"],
    )
