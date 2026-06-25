from datetime import datetime

from pydantic import BaseModel


class BricklinkMappingOut(BaseModel):
    part_no: str | None
    color_id: int | None
    item_type: str | None
    part_name: str | None
    source: str | None

    model_config = {"from_attributes": True}


class StudioResolutionOut(BaseModel):
    part_no: str
    part_file: str | None
    source_type: str | None
    resolution_method: str | None
    resolved_from: str | None
    studio_color_id: int | None
    resolved: bool

    model_config = {"from_attributes": True}


class LocalePriceResult(BaseModel):
    element_id: int
    design_id: str | None
    lego_name: str | None
    locale: str
    channel: str | None
    price_cents: int | None
    price_formatted: str | None
    currency_code: str | None
    in_stock: bool | None

    model_config = {"from_attributes": True}


class PartSummary(BaseModel):
    element_id: int
    design_id: str | None
    lego_name: str | None
    channel: str | None
    price_cents: int | None
    price_formatted: str | None

    model_config = {"from_attributes": True}


class PartDetail(BaseModel):
    element_id: int
    design_id: str | None
    lego_name: str | None
    channel: str | None
    price_cents: int | None
    price_formatted: str | None
    last_seen: datetime | None
    first_seen: datetime | None
    bricklink_mapping: BricklinkMappingOut | None

    model_config = {"from_attributes": True}
