"""Schemas für Standort, Equipment, Settings (Phase 2)."""

from pydantic import BaseModel, Field


# ─── Location ───
class LocationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation_m: float | None = None
    timezone: str | None = None
    bortle: int | None = Field(default=None, ge=1, le=9)
    meteoblue_url: str | None = Field(default=None, max_length=500)
    is_default: bool = False


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation_m: float | None = None
    timezone: str | None = None
    bortle: int | None = Field(default=None, ge=1, le=9)
    meteoblue_url: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None


class LocationOut(LocationBase):
    id: str


# ─── Telescope ───
class TelescopeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    aperture_mm: float | None = Field(default=None, gt=0)
    focal_length_mm: float | None = Field(default=None, gt=0)
    limiting_magnitude: float | None = Field(default=None, ge=0, le=25)
    notes: str | None = None


class TelescopeCreate(TelescopeBase):
    pass


class TelescopeOut(TelescopeBase):
    id: str
    focal_ratio: float | None = None
    # Vorschlag aus der Öffnung (stellare Grenzgröße) — UI darf vorbelegen.
    suggested_limiting_magnitude: float | None = None


# ─── Camera ───
class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    pixel_size_um: float | None = Field(default=None, gt=0)
    res_x: int | None = Field(default=None, gt=0)
    res_y: int | None = Field(default=None, gt=0)
    sensor_type: str = Field(default="color", pattern="^(color|mono)$")


class CameraCreate(CameraBase):
    pass


class CameraOut(CameraBase):
    id: str


# ─── Filter ───
class FilterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field(default="broadband", pattern="^(broadband|narrowband)$")
    bandwidth_nm: float | None = Field(default=None, gt=0, le=300)


class FilterCreate(FilterBase):
    pass


class FilterOut(FilterBase):
    id: str


# ─── Setup (Teleskop + Kamera + Filter) ───
class SetupCreate(BaseModel):
    telescope_id: str
    camera_id: str
    name: str | None = Field(default=None, max_length=160)
    filter_ids: list[str] = []
    calibration_dir: str | None = Field(default=None, max_length=500)


class SetupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    filter_ids: list[str] | None = None
    calibration_dir: str | None = Field(default=None, max_length=500)


class SetupFilterOut(BaseModel):
    id: str
    name: str
    kind: str
    bandwidth_nm: float | None = None


class SetupOut(BaseModel):
    id: str
    name: str
    telescope_id: str
    telescope_name: str
    camera_id: str
    camera_name: str
    focal_ratio: float | None = None
    filters: list[SetupFilterOut] = []
    calibration_dir: str | None = None


# ─── Settings ───
class SettingsOut(BaseModel):
    night_start: str = "22:00"
    night_end: str = "05:00"
    default_location_id: str | None = None
    # Archiv-Wurzel (Containerpfad zur gemounteten NAS) für den Foto-Workflow.
    archive_root: str = "/archive"


class SettingsUpdate(BaseModel):
    night_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    night_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    default_location_id: str | None = None
    archive_root: str | None = Field(default=None, max_length=500)
