"""Upload, Analyse, JPG-Konvertierung & Download von Astro-Bildern (Phase 6)."""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.image import Image
from app.models.observation import Observation
from app.models.user import User
from app.schemas.image import ImageOut
from app.services import image_processing

router = APIRouter(tags=["images"])
settings = get_settings()

_BASE = Path(settings.outputs_dir) / "images"
_EXT_FORMAT = {
    ".fits": "fits", ".fit": "fits", ".fts": "fits",
    ".xisf": "xisf",
    ".tif": "tiff", ".tiff": "tiff",
}


def _out(img: Image) -> ImageOut:
    return ImageOut(
        id=str(img.id),
        observation_id=str(img.observation_id),
        original_format=img.original_format,
        original_filename=img.original_filename,
        file_size=img.file_size,
        width=img.width,
        height=img.height,
        channels=img.channels,
        meta_summary=(img.extracted_meta or {}).get("summary", {}),
        created_at=img.created_at.isoformat() if img.created_at else None,
        jpg_url=f"/api/images/{img.id}/jpg",
        download_url=f"/api/images/{img.id}/download",
    )


async def _owned_observation(db: AsyncSession, user: User, obs_id: str) -> Observation:
    try:
        o = await db.scalar(
            select(Observation).where(Observation.id == uuid.UUID(obs_id), Observation.user_id == user.id)
        )
    except ValueError:
        o = None
    if not o:
        raise HTTPException(404, "Aufnahme nicht gefunden")
    return o


async def _owned_image(db: AsyncSession, user: User, image_id: str) -> Image:
    try:
        img = await db.scalar(select(Image).where(Image.id == uuid.UUID(image_id), Image.user_id == user.id))
    except ValueError:
        img = None
    if not img:
        raise HTTPException(404, "Bild nicht gefunden")
    return img


@router.get("/api/observations/{obs_id}/images", response_model=list[ImageOut])
async def list_images(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_observation(db, user, obs_id)
    rows = await db.scalars(
        select(Image).where(Image.observation_id == uuid.UUID(obs_id)).order_by(Image.created_at.desc())
    )
    return [_out(i) for i in rows]


@router.post("/api/observations/{obs_id}/images", response_model=ImageOut, status_code=201)
async def upload_image(
    obs_id: str, file: UploadFile, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    obs = await _owned_observation(db, user, obs_id)
    ext = Path(file.filename or "").suffix.lower()
    fmt = _EXT_FORMAT.get(ext)
    if not fmt:
        raise HTTPException(400, "Format nicht unterstützt (FITS, XISF, TIFF).")

    image_id = uuid.uuid4()
    orig_dir = _BASE / "orig"
    jpg_dir = _BASE / "jpg"
    orig_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir.mkdir(parents=True, exist_ok=True)
    orig_path = orig_dir / f"{image_id}{ext}"
    jpg_path = jpg_dir / f"{image_id}.jpg"

    # Streamend auf Platte schreiben (große FITS/XISF nicht komplett in RAM).
    size = 0
    with open(orig_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
            size += len(chunk)

    try:
        info = await asyncio.to_thread(image_processing.process, str(orig_path), fmt, str(jpg_path))
    except Exception as e:
        orig_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Analyse/Konvertierung fehlgeschlagen: {e}")

    img = Image(
        id=image_id,
        user_id=user.id,
        observation_id=obs.id,
        original_format=fmt,
        original_filename=file.filename or f"upload{ext}",
        file_path=str(orig_path),
        jpg_path=str(jpg_path),
        file_size=size,
        width=info["width"],
        height=info["height"],
        channels=info["channels"],
        extracted_meta=info["meta"],
    )
    db.add(img)
    obs.is_new = False  # Foto hochgeladen → Aufnahme nicht mehr „neu".
    await db.flush()
    return _out(img)


@router.get("/api/images/{image_id}/jpg")
async def image_jpg(image_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    img = await _owned_image(db, user, image_id)
    if not img.jpg_path or not Path(img.jpg_path).exists():
        raise HTTPException(404, "JPG nicht vorhanden")
    return FileResponse(img.jpg_path, media_type="image/jpeg")


@router.get("/api/images/{image_id}/download")
async def image_download(image_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    img = await _owned_image(db, user, image_id)
    if not img.jpg_path or not Path(img.jpg_path).exists():
        raise HTTPException(404, "JPG nicht vorhanden")
    name = Path(img.original_filename).stem + ".jpg"
    return FileResponse(img.jpg_path, media_type="image/jpeg", filename=name)


@router.delete("/api/images/{image_id}", status_code=204)
async def delete_image(image_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    img = await _owned_image(db, user, image_id)
    for p in (img.file_path, img.jpg_path):
        if p:
            Path(p).unlink(missing_ok=True)
    await db.delete(img)
