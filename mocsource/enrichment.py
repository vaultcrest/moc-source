"""Database enrichment: cross-reference BL parts with Rebrickable to fill element ID gaps."""

import asyncio
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import settings
from .database import AsyncSessionLocal
from .models import BricklinkMapping, LegoElement
from .rebrickable_client import find_elements, get_bl_to_rb_color_map

log = logging.getLogger(__name__)


async def enrich_bl_part_bg(
    part_no: str,
    bl_color_id: int,
    alternates: list[str],
    part_name: str | None,
) -> None:
    """Background task: find LEGO element IDs via Rebrickable and upsert into the DB.

    Uses its own DB session — safe to run after the HTTP response is sent.
    """
    if not settings.rebrickable_api_key:
        return

    color_map = await get_bl_to_rb_color_map()
    rb_color_id = color_map.get(bl_color_id)
    if rb_color_id is None:
        log.info("enrich_bl_part: no RB color mapping for BL color %s (part %s)", bl_color_id, part_no)
        return

    resolved_via, element_ids = await find_elements(part_no, alternates, rb_color_id)
    if not element_ids:
        log.info("enrich_bl_part: Rebrickable found no elements for %s bl_color=%s", part_no, bl_color_id)
        return

    now = datetime.utcnow()
    newly_added: list[int] = []
    skipped: list[int] = []

    async with AsyncSessionLocal() as db:
        for element_id in element_ids:
            existing = await db.get(LegoElement, element_id)
            if existing and existing.lego_name:
                skipped.append(element_id)
                # Still try to fill the BL mapping if missing
                existing_map = await db.get(BricklinkMapping, element_id)
                if not existing_map:
                    db.add(BricklinkMapping(
                        element_id=element_id,
                        part_no=part_no,
                        color_id=bl_color_id,
                        item_type="PART",
                        part_name=part_name,
                        source="rebrickable",
                        updated_at=now,
                    ))
                continue

            # Upsert lego_element (preserve existing name/price if present)
            stmt = pg_insert(LegoElement.__table__).values(
                element_id=element_id,
                first_seen=now,
                last_seen=now,
            ).on_conflict_do_update(
                index_elements=["element_id"],
                set_={"last_seen": now},
            )
            await db.execute(stmt)

            # Upsert bricklink_mapping
            stmt = pg_insert(BricklinkMapping.__table__).values(
                element_id=element_id,
                part_no=part_no,
                color_id=bl_color_id,
                item_type="PART",
                part_name=part_name,
                source="rebrickable",
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["element_id"],
                set_={
                    "part_no": part_no,
                    "color_id": bl_color_id,
                    "part_name": part_name,
                    "source": "rebrickable",
                    "updated_at": now,
                },
            )
            await db.execute(stmt)
            newly_added.append(element_id)

        await db.commit()

    log.info(
        "enrich_bl_part: %s bl_color=%s → resolved via %s, added=%s, skipped=%s",
        part_no, bl_color_id, resolved_via, newly_added, skipped,
    )

    await asyncio.to_thread(
        _send_enrichment_email,
        part_no, bl_color_id, resolved_via, alternates,
        part_name, newly_added, skipped,
    )


def _send_enrichment_email(
    part_no: str,
    bl_color_id: int,
    resolved_via: str,
    alternates: list[str],
    part_name: str | None,
    newly_added: list[int],
    skipped: list[int],
) -> None:
    if not settings.smtp_host or not settings.report_email:
        return

    lines = [
        "MOC Source — Rebrickable Enrichment Report",
        "=" * 50,
        f"BL Part:      {part_no}",
        f"BL Color ID:  {bl_color_id}",
        f"Part Name:    {part_name or '(unknown)'}",
        f"Alternates:   {', '.join(alternates) or 'none'}",
        f"Resolved via: {resolved_via or '(none)'}",
        "",
        f"Elements newly added ({len(newly_added)}): {newly_added}",
        f"Elements already in DB ({len(skipped)}): {skipped}",
        "",
        f"Timestamp: {datetime.utcnow().isoformat()} UTC",
    ]

    msg = MIMEText("\n".join(lines))
    msg["Subject"] = f"[MOC Source] Enrichment: {part_no} / BL color {bl_color_id} → {len(newly_added)} new elements"
    msg["From"] = settings.smtp_from
    msg["To"] = settings.report_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_from, [settings.report_email], msg.as_string())
        log.info("Enrichment email sent to %s", settings.report_email)
    except Exception as e:
        log.warning("Failed to send enrichment email: %s", e)
