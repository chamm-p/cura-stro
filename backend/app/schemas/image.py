"""Schemas für hochgeladene Bilder (Phase 6)."""

from pydantic import BaseModel


class ImageOut(BaseModel):
    id: str
    observation_id: str
    original_format: str
    original_filename: str
    file_size: int | None
    width: int | None
    height: int | None
    channels: int | None
    meta_summary: dict
    created_at: str | None
    jpg_url: str
    download_url: str
