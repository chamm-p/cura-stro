"""Schemas für ASIAir-Rigs (V2 Phase A)."""

from pydantic import BaseModel, Field


class RigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=255)
    share: str | None = Field(default=None, max_length=255)
    telescope_id: str | None = None


class RigCreate(RigBase):
    pass


class RigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=255)
    share: str | None = Field(default=None, max_length=255)
    telescope_id: str | None = None


class RigOut(RigBase):
    id: str
    telescope_name: str | None = None
    marker_id: str | None = None
