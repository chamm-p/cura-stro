"""ASIAir-Rig-CRUD (V2 Phase A) — Mapping ASIAir ↔ Teleskop.

Eine ASIAir je Gerät: das Mapping liefert den ``<Gerät>``-Ordner beim Import
(Phase B), da der Dateiname das Teleskop nicht enthält.
"""

import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.asiair import AsiairRig
from app.models.catalog import CatalogObject
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.subframe import SubFrame
from app.models.user import User
from app.schemas.asiair import RigCreate, RigOut, RigUpdate
from app.services import archive
from app.services import asiair as asi
from app.services import discovery
from app.services.asiair_smb import AsiairClient, AsiairError, detect_share, read_marker, write_marker

router = APIRouter(prefix="/api/asiair", tags=["asiair"])
_settings = get_settings()
_TMP = os.path.join(_settings.outputs_dir, "tmp")


def _out(r: AsiairRig, scope: Telescope | None) -> RigOut:
    return RigOut(
        id=str(r.id),
        name=r.name,
        host=r.host,
        share=r.share,
        telescope_id=str(r.telescope_id) if r.telescope_id else None,
        telescope_name=scope.name if scope else None,
        marker_id=r.marker_id,
    )


async def _write_marker(rig: AsiairRig) -> None:
    """Marker-Datei (Rig-Kennung + Name) best-effort auf die Freigabe schreiben."""
    if not (rig.host and rig.share and rig.marker_id):
        return
    try:
        await asyncio.to_thread(write_marker, rig.host, rig.share,
                                {"id": rig.marker_id, "name": rig.name, "app": "cura-stro"})
    except Exception:  # noqa: BLE001
        pass


def _subnet_of(host: str | None) -> str:
    if host and host.count(".") == 3:
        a, b, c, _ = host.split(".")
        return f"{a}.{b}.{c}.0/24"
    return "192.168.0.0/24"


async def _live_host(db: AsyncSession, rig: AsiairRig) -> str:
    """Aktuelle IP der ASIAir ermitteln — bei IP-Wechsel per Marker wiederfinden.
    Aktualisiert rig.host, wenn die ASIAir an neuer IP gefunden wurde."""
    if rig.host and await discovery.asiair_info(rig.host):
        return rig.host  # gespeicherte IP erreichbar
    if not (rig.marker_id and rig.share):
        return rig.host or ""
    for a in await discovery.scan_subnet(_subnet_of(rig.host)):
        m = await asyncio.to_thread(read_marker, a["ip"], rig.share)
        if m and m.get("id") == rig.marker_id:
            if a["ip"] != rig.host:
                rig.host = a["ip"]
                await db.flush()
            return a["ip"]
    return rig.host or ""


async def _uuid_or_none(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(400, "Ungültige ID")


async def _scope(db: AsyncSession, user: User, scope_id: uuid.UUID | None) -> Telescope | None:
    if not scope_id:
        return None
    scope = await db.scalar(select(Telescope).where(Telescope.id == scope_id, Telescope.user_id == user.id))
    if not scope:
        raise HTTPException(404, "Teleskop nicht gefunden")
    return scope


@router.get("/rigs", response_model=list[RigOut])
async def list_rigs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(AsiairRig).where(AsiairRig.user_id == user.id).order_by(AsiairRig.name)))
    scopes = {t.id: t for t in await db.scalars(select(Telescope).where(Telescope.user_id == user.id))}
    return [_out(r, scopes.get(r.telescope_id)) for r in rows]


@router.post("/rigs", response_model=RigOut, status_code=201)
async def create_rig(body: RigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope_id = await _uuid_or_none(body.telescope_id)
    scope = await _scope(db, user, scope_id)
    share = body.share or None
    if not share and body.host:  # Freigabe automatisch erkennen
        try:
            share = await asyncio.to_thread(detect_share, body.host)
        except Exception:  # noqa: BLE001
            share = None
    r = AsiairRig(
        user_id=user.id, name=body.name, host=body.host or None, share=share,
        telescope_id=scope_id, marker_id=uuid.uuid4().hex,
    )
    db.add(r)
    await db.flush()
    await _write_marker(r)  # Marker auf die ASIAir schreiben (best-effort)
    return _out(r, scope)


async def _owned(db: AsyncSession, user: User, rig_id: str) -> AsiairRig:
    rid = await _uuid_or_none(rig_id)
    r = await db.scalar(select(AsiairRig).where(AsiairRig.id == rid, AsiairRig.user_id == user.id))
    if not r:
        raise HTTPException(404, "ASIAir nicht gefunden")
    return r


@router.patch("/rigs/{rig_id}", response_model=RigOut)
async def update_rig(
    rig_id: str, body: RigUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await _owned(db, user, rig_id)
    data = body.model_dump(exclude_unset=True)
    if "telescope_id" in data:
        scope_id = await _uuid_or_none(data.pop("telescope_id"))
        await _scope(db, user, scope_id)
        r.telescope_id = scope_id
    for k in ("name", "host", "share"):
        if k in data:
            setattr(r, k, data[k] or None if k != "name" else data[k])
    if not r.marker_id:
        r.marker_id = uuid.uuid4().hex
    if r.host and not r.share:  # Freigabe automatisch erkennen
        try:
            r.share = await asyncio.to_thread(detect_share, r.host)
        except Exception:  # noqa: BLE001
            pass
    await db.flush()
    await _write_marker(r)  # Marker aktualisieren (Name/Kennung) — best-effort
    scope = await db.get(Telescope, r.telescope_id) if r.telescope_id else None
    return _out(r, scope)


@router.delete("/rigs/{rig_id}", status_code=204)
async def delete_rig(rig_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, user, rig_id))


# ─── ASIAir-Direktimport (SMB) ───
def _client(rig: AsiairRig) -> AsiairClient:
    try:
        return AsiairClient(rig.host or "", rig.share or "")
    except AsiairError as e:
        raise HTTPException(400, str(e))


async def _catalog_map(db: AsyncSession) -> dict[str, CatalogObject]:
    """normalisierte Ident → CatalogObject (z. B. 'IC417' → …)."""
    rows = await db.scalars(select(CatalogObject))
    out: dict[str, CatalogObject] = {}
    for o in rows:
        if o.ident:
            out.setdefault(asi.normalize_object(o.ident), o)
    return out


def _group(files: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for f in files:
        p = f["parsed"]
        key = asi.normalize_object(p.object_name)
        g = groups.setdefault(key, {
            "object": p.object_name, "normalized": key,
            "subs": 0, "filters": {}, "nights": set(), "files": [],
        })
        g["subs"] += 1
        fn = p.filter_name or "—"
        g["filters"][fn] = g["filters"].get(fn, 0) + 1
        if p.captured_at:
            g["nights"].add(p.captured_at.date().isoformat())
        g["files"].append(f)
    return groups


@router.get("/rigs/{rig_id}/scan")
async def scan_rig(rig_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rig = await _owned(db, user, rig_id)
    await _live_host(db, rig)  # IP per Marker auffrischen (falls gewechselt)
    client = _client(rig)
    try:
        files = await asyncio.to_thread(client.scan)
    except AsiairError as e:
        raise HTTPException(502, str(e))
    cat = await _catalog_map(db)
    groups = _group(files)
    out = []
    for key, g in sorted(groups.items()):
        match = cat.get(key)
        out.append({
            "object": g["object"], "normalized": key,
            "matched_ident": match.ident if match else None,
            "matched_name": match.name if match else None,
            "subs": g["subs"],
            "filters": [{"filter": k, "subs": v} for k, v in sorted(g["filters"].items())],
            "nights": len(g["nights"]),
        })
    scope = await db.get(Telescope, rig.telescope_id) if rig.telescope_id else None
    return {"total_files": len(files), "telescope": scope.name if scope else None, "objects": out}


async def _upsert_observation(db: AsyncSession, user: User, cat: CatalogObject | None,
                              label: str, telescope_id) -> Observation:
    q = select(Observation).where(Observation.user_id == user.id)
    if cat:
        q = q.where(Observation.catalog_object_id == cat.id)
    else:
        q = q.where(Observation.target_label == label, Observation.catalog_object_id.is_(None))
    q = q.where(Observation.telescope_id == telescope_id if telescope_id else Observation.telescope_id.is_(None))
    obs = await db.scalar(q)
    if not obs:
        obs = Observation(
            user_id=user.id, catalog_object_id=cat.id if cat else None,
            target_label=None if cat else label, status="geplant",
            telescope_id=telescope_id, is_new=True,
        )
        db.add(obs)
        await db.flush()
    return obs


class ImportBody(BaseModel):
    objects: list[str] | None = None  # normalisierte Keys; None = alle
    cleanup: bool = False             # nach Import verifizierte Subs auf ASIAir löschen


@router.post("/rigs/{rig_id}/import")
async def import_rig(
    rig_id: str, body: ImportBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rig = await _owned(db, user, rig_id)
    if not rig.telescope_id:
        raise HTTPException(400, "Diesem ASIAir ist kein Teleskop zugeordnet — in den Einstellungen setzen.")
    await _live_host(db, rig)  # IP per Marker auffrischen (falls gewechselt)
    client = _client(rig)
    try:
        files = await asyncio.to_thread(client.scan)
    except AsiairError as e:
        raise HTTPException(502, str(e))

    cat = await _catalog_map(db)
    groups = _group(files)
    selected = set(body.objects) if body.objects else None

    imported = []
    cleaned = 0
    for key, g in groups.items():
        if selected is not None and key not in selected:
            continue
        match = cat.get(key)
        obs = await _upsert_observation(db, user, match, g["object"], rig.telescope_id)

        filed = dup = err = 0
        cleanup_paths: list[str] = []
        # In kleinen Häppchen lesen → Temp-Disk begrenzen.
        for i in range(0, len(g["files"]), 10):
            chunk = g["files"][i:i + 10]
            items, temps = [], []
            for f in chunk:
                try:
                    tmp, _sz = await asyncio.to_thread(client.read_to_temp, f["path"], _TMP)
                except Exception:  # noqa: BLE001
                    err += 1
                    continue
                items.append((f["name"], tmp, f["path"]))
                temps.append(tmp)
            if items:
                res = await archive.import_files(db, user, obs, items, source="asiair")
                filed += res["filed"]
                dup += res["duplicates"]
                err += res.get("errors", 0)
                # Erfolgreich abgelegte (nicht-Dubletten) → Cleanup-Kandidaten.
                done = {r["file"] for r in res["results"] if r["status"] == "filed"}
                cleanup_paths += [f["path"] for f in chunk if f["name"] in done]
            for t in temps:
                try:
                    os.unlink(t)
                except OSError:
                    pass

        if body.cleanup and cleanup_paths:
            for p in cleanup_paths:
                try:
                    await asyncio.to_thread(client.delete, p)
                    cleaned += 1
                except Exception:  # noqa: BLE001
                    pass

        imported.append({
            "object": g["object"], "matched_ident": match.ident if match else None,
            "filed": filed, "duplicates": dup, "errors": err,
        })

    return {"imported": imported, "cleaned": cleaned,
            "total_filed": sum(x["filed"] for x in imported)}


class CleanupBody(BaseModel):
    object: str | None = None  # normalisierter Key; None = alle


@router.post("/rigs/{rig_id}/cleanup")
async def cleanup_rig(
    rig_id: str, body: CleanupBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Löscht auf der ASIAir nur Subs, die nachweislich (verified) im Archiv
    liegen und einen bekannten Quellpfad haben."""
    rig = await _owned(db, user, rig_id)
    client = _client(rig)

    q = (
        select(SubFrame)
        .join(Observation, Observation.id == SubFrame.observation_id)
        .where(
            SubFrame.user_id == user.id,
            SubFrame.source == "asiair",
            SubFrame.verified.is_(True),
            SubFrame.source_path.is_not(None),
            Observation.telescope_id == rig.telescope_id,
        )
    )
    subs = list(await db.scalars(q))
    if body.object:
        # Nur Subs des gewählten Objekts.
        keep = []
        for s in subs:
            obs = await db.get(Observation, s.observation_id)
            label = await archive.object_label(db, obs)
            if asi.normalize_object(label) == body.object:
                keep.append(s)
        subs = keep

    deleted = errors = 0
    for s in subs:
        try:
            await asyncio.to_thread(client.delete, s.source_path)
            s.source_path = None  # als aufgeräumt markieren
            deleted += 1
        except Exception:  # noqa: BLE001
            errors += 1
    await db.flush()
    return {"deleted": deleted, "errors": errors, "candidates": len(subs)}


_STD_SHARES = ["EMMC Images", "Udisk Images", "TF Images"]


@router.get("/discover")
async def discover(
    subnet: str = "192.168.0.0/24",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Findet echte ASIAirs im Subnetz (Port 4400 + Banner) inkl. Gerätename.
    Liest zusätzlich die Marker-Datei → zeigt registrierte ASIAirs unter ihrem
    Rig-Namen (IP-unabhängig)."""
    try:
        airs = await discovery.scan_subnet(subnet)
    except ValueError:
        raise HTTPException(400, "Ungültiges Subnetz (z. B. 192.168.0.0/24).")
    rigs = {r.marker_id: r for r in await db.scalars(
        select(AsiairRig).where(AsiairRig.user_id == user.id)) if r.marker_id}
    for a in airs:
        for sh in _STD_SHARES:
            m = await asyncio.to_thread(read_marker, a["ip"], sh)
            if m and m.get("id"):
                a["marker_id"] = m["id"]
                a["marker_name"] = m.get("name")
                a["share"] = sh
                rig = rigs.get(m["id"])
                if rig:
                    a["registered_rig_id"] = str(rig.id)
                    a["registered_rig_name"] = rig.name
                break
    return {"subnet": subnet, "asiairs": airs}
