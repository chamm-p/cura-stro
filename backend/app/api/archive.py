"""Archiv-Konfiguration + Status (V2) — NAS direkt per SMB, im UI konfigurierbar.

- GET  /api/archive/config  → aktuelle Konfig (Passwort maskiert)
- PUT  /api/archive/config  → Modus (lokal/smb) + NAS-Zugang speichern
- POST /api/archive/test    → Verbindung testen (mit Formularwerten ODER gespeichert)
- GET  /api/archive/status  → Live-Status des aktiven Backends
"""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import archive as arch
from app.services.storage import SmbStorage

router = APIRouter(prefix="/api/archive", tags=["archive"])


class NasIn(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    share: str | None = Field(default=None, max_length=255)
    path: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=255)
    # Leer/weggelassen → vorhandenes Passwort beibehalten.
    password: str | None = Field(default=None, max_length=255)


class ConfigIn(BaseModel):
    mode: str = Field(default="local", pattern="^(local|smb)$")
    root: str | None = Field(default=None, max_length=500)
    nas: NasIn | None = None


def _config_out(user: User) -> dict:
    cfg = arch.archive_config(user)
    nas = cfg.get("nas") or {}
    return {
        "mode": cfg["mode"],
        "root": cfg["root"],
        "nas": {
            "host": nas.get("host") or "",
            "share": nas.get("share") or "",
            "path": nas.get("path") or "",
            "username": nas.get("username") or "",
            "password_set": bool(nas.get("password")),
        },
    }


@router.get("/config")
async def get_config(user: User = Depends(get_current_user)):
    return _config_out(user)


@router.put("/config")
async def put_config(body: ConfigIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    settings = dict(user.settings or {})
    a = dict(settings.get("archive") or {})
    a["mode"] = body.mode
    if body.root is not None:
        a["root"] = body.root or None
    if body.nas is not None:
        nas = dict(a.get("nas") or {})
        for k in ("host", "share", "path", "username"):
            v = getattr(body.nas, k)
            if v is not None:
                nas[k] = v.strip() or None
        # Passwort nur überschreiben, wenn ein nicht-leeres geliefert wird.
        if body.nas.password:
            nas["password"] = body.nas.password
        a["nas"] = nas
    settings["archive"] = a
    user.settings = settings  # Reassign → JSONB-Änderung erkannt.
    await db.flush()
    return _config_out(user)


def _override_from(body: ConfigIn | None, user: User) -> dict:
    """Konfig zum Testen: Formularwerte bevorzugen, Passwort ggf. aus DB ziehen."""
    if not body:
        return arch.archive_config(user)
    stored = arch.archive_config(user).get("nas") or {}
    nas = {}
    if body.nas:
        nas = {
            "host": body.nas.host, "share": body.nas.share, "path": body.nas.path,
            "username": body.nas.username,
            "password": body.nas.password or stored.get("password"),
        }
    return {"mode": body.mode, "root": body.root or arch._cfg.archive_root, "nas": nas}


@router.post("/test")
async def test_config(
    body: ConfigIn | None = None, user: User = Depends(get_current_user)
):
    cfg = _override_from(body, user)
    storage = arch.get_storage(user, override=cfg)
    status = await asyncio.to_thread(storage.status)
    ok = bool(status.get("writable"))
    return {"ok": ok, "status": status}


@router.get("/status")
async def get_status(user: User = Depends(get_current_user)):
    storage = arch.get_storage(user)
    status = await asyncio.to_thread(storage.status)
    return status
