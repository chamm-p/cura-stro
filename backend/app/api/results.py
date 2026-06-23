"""PixInsight-Ergebnisbilder (V2 Phase C).

Upload ins NAS-Archiv (``Developer/<Objekt>/<Gerät>/``), Auflistung, On-Demand-
Scan des Developer-Ordners (Watch), gestreckte Vorschau, Download, Löschen.
"""

import asyncio
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.observation import Observation
from app.models.result_file import ResultFile
from app.models.user import User
from app.services import archive, image_processing, results

router = APIRouter(tags=["results"])
settings = get_settings()
_TMP = Path(settings.outputs_dir) / "tmp"
_PREV = Path(settings.outputs_dir) / "resultprev"
_FMT = {".fit": "fits", ".fits": "fits", ".fts": "fits", ".xisf": "xisf", ".tif": "tiff", ".tiff": "tiff"}


async def _owned_obs(db: AsyncSession, user: User, obs_id: str) -> Observation:
    try:
        o = await db.scalar(select(Observation).where(Observation.id == uuid.UUID(obs_id), Observation.user_id == user.id))
    except ValueError:
        o = None
    if not o:
        raise HTTPException(404, "Aufnahme nicht gefunden")
    return o


async def _owned_result(db: AsyncSession, user: User, rid: str) -> ResultFile:
    try:
        r = await db.scalar(select(ResultFile).where(ResultFile.id == uuid.UUID(rid), ResultFile.user_id == user.id))
    except ValueError:
        r = None
    if not r:
        raise HTTPException(404, "Ergebnis nicht gefunden")
    return r


def _out(r: ResultFile) -> dict:
    return {
        "id": str(r.id), "filename": r.filename, "file_size": r.file_size,
        "width": r.width, "height": r.height, "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "preview_url": f"/api/results/{r.id}/preview",
        "download_url": f"/api/results/{r.id}/download",
    }


@router.get("/api/observations/{obs_id}/results")
async def list_results(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    obs = await _owned_obs(db, user, obs_id)
    rows = await db.scalars(select(ResultFile).where(ResultFile.observation_id == obs.id).order_by(ResultFile.created_at.desc()))
    return [_out(r) for r in rows]


@router.post("/api/observations/{obs_id}/result", status_code=201)
async def upload_result(
    obs_id: str, file: UploadFile, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    obs = await _owned_obs(db, user, obs_id)
    name = PurePosixPath((file.filename or "ergebnis").replace("\\", "/")).name
    if PurePosixPath(name).suffix.lower() not in results.RESULT_EXTS:
        raise HTTPException(400, "Format nicht unterstützt (XISF/TIFF/FITS/JPG/PNG).")
    if await db.scalar(select(ResultFile).where(ResultFile.observation_id == obs.id, ResultFile.filename == name)):
        raise HTTPException(409, "Ein Ergebnis mit diesem Dateinamen existiert bereits.")

    _TMP.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_TMP, suffix=PurePosixPath(name).suffix)
    os.close(fd)
    try:
        size = 0
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        reld = await results.developer_reldir(db, user, obs)
        storage = archive.get_storage(user)
        rel = f"{reld}/{name}"
        await asyncio.to_thread(storage.put, rel, tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    r = ResultFile(user_id=user.id, observation_id=obs.id, filename=name,
                   archive_path=storage.full_path(rel), file_size=size, source="upload")
    db.add(r)
    if obs.status != "entwickelt":
        obs.status = "entwickelt"
    obs.is_new = False
    await db.flush()
    return _out(r)


@router.post("/api/observations/{obs_id}/results/scan")
async def scan_results(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Developer-Ordner jetzt einlesen (Watch on-demand)."""
    obs = await _owned_obs(db, user, obs_id)
    added = await results.scan_import(db, user, obs, source="watch")
    rows = await db.scalars(select(ResultFile).where(ResultFile.observation_id == obs.id).order_by(ResultFile.created_at.desc()))
    return {"added": added, "results": [_out(r) for r in rows]}


def _make_preview(src: str, fmt: str | None, dest: str) -> None:
    if fmt:
        image_processing.process(src, fmt, dest)
    else:  # JPG/PNG → direkt skalieren
        from PIL import Image
        Image.open(src).convert("RGB").save(dest, "JPEG", quality=88)
    # auf handliche Größe verkleinern
    from PIL import Image
    im = Image.open(dest)
    if max(im.size) > 1600:
        im.thumbnail((1600, 1600))
        im.save(dest, "JPEG", quality=88)


@router.get("/api/results/{rid}/preview")
async def result_preview(rid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await _owned_result(db, user, rid)
    _PREV.mkdir(parents=True, exist_ok=True)
    cache = _PREV / f"{r.id}.jpg"
    if cache.exists():
        return FileResponse(cache, media_type="image/jpeg")
    obs = await db.get(Observation, r.observation_id)
    reld = await results.developer_reldir(db, user, obs)
    rel = f"{reld}/{r.filename}"
    fmt = _FMT.get(PurePosixPath(r.filename).suffix.lower())
    _TMP.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_TMP, suffix=PurePosixPath(r.filename).suffix)
    os.close(fd)
    try:
        await asyncio.to_thread(archive.get_storage(user).fetch, rel, tmp)
        await asyncio.to_thread(_make_preview, tmp, fmt, str(cache))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Vorschau fehlgeschlagen: {e}")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return FileResponse(cache, media_type="image/jpeg")


@router.get("/api/results/{rid}/download")
async def result_download(rid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await _owned_result(db, user, rid)
    obs = await db.get(Observation, r.observation_id)
    reld = await results.developer_reldir(db, user, obs)
    rel = f"{reld}/{r.filename}"
    _TMP.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_TMP, suffix=PurePosixPath(r.filename).suffix)
    os.close(fd)
    try:
        await asyncio.to_thread(archive.get_storage(user).fetch, rel, tmp)
    except Exception as e:  # noqa: BLE001
        os.unlink(tmp)
        raise HTTPException(422, f"Download fehlgeschlagen: {e}")
    return FileResponse(tmp, media_type="application/octet-stream", filename=r.filename,
                        background=BackgroundTask(lambda: os.path.exists(tmp) and os.unlink(tmp)))


@router.delete("/api/observations/{obs_id}/results/{rid}", status_code=204)
async def delete_result(obs_id: str, rid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Entfernt die Registrierung + Vorschau-Cache. Die Datei im Developer-Baum
    (dein PixInsight-Output) bleibt erhalten."""
    await _owned_obs(db, user, obs_id)
    r = await _owned_result(db, user, rid)
    (_PREV / f"{r.id}.jpg").unlink(missing_ok=True)
    await db.delete(r)
