"""Datei-Import (Drag & Drop) — Subs aus beliebiger Quelle einsortieren.

Ergänzt den ASIAir-Direktimport: der Nutzer zieht einen Ordnerbaum in den
Browser, dessen Struktur immer ``…/<Objektname>/<Gerätename>/*.fit`` ist
(z. B. ``Astrofotos/Raw-Files/C4/RC71/Light_C4_300.0s_….fit``).

Ablauf:
    1. POST /api/import/preview — nur die relativen Pfade (kein Inhalt).
       Gruppiert nach (Objekt, Gerät), matcht Objekt gegen den Katalog und
       Gerät gegen die Teleskope, meldet unparsbare Dateien.
    2. POST /api/import/file — eine Datei pro Request (multipart), mit
       object_name/device_name aus der (ggf. korrigierten) Vorschau.
       Nutzt dieselbe Pipeline wie der ASIAir-Import: find-or-create
       Observation, Ablage unter RAW/<Objekt>/<Gerät>/, SubFrame-Zeile
       mit Dublettenschutz. Das Frontend lädt sequenziell hoch und hat
       damit einen exakten Fortschritt.
"""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.asiair import _catalog_map
from app.api.deps import get_current_user
from app.database import get_db
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive
from app.services import asiair as asi

router = APIRouter(prefix="/api/import", tags=["import"])

RAW_EXTS = {".fit", ".fits", ".fts"}


def _split_group(rel_path: str) -> tuple[str, str, str]:
    """Zerlegt einen relativen Pfad in (Objekt, Gerät, Dateiname).

    Regel: die letzten beiden Ordner vor der Datei sind Objekt/Gerät.
    Fehlt Tiefe (Datei direkt in einem Ordner oder lose), bleiben die
    Felder leer — der Nutzer korrigiert sie in der Vorschau."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    name = parts[-1] if parts else ""
    device = parts[-2] if len(parts) >= 3 else ""
    obj = parts[-3] if len(parts) >= 3 else (parts[-2] if len(parts) == 2 else "")
    return obj, device, name


async def _telescope_by_name(db: AsyncSession, user: User, name: str) -> Telescope | None:
    if not name.strip():
        return None
    rows = await db.scalars(select(Telescope).where(Telescope.user_id == user.id))
    for t in rows:
        if (t.name or "").strip().lower() == name.strip().lower():
            return t
    return None


async def _matching_observations(
    db: AsyncSession, user: User, cat, label: str, telescope_id
) -> list[Observation]:
    """Alle Aufnahmen zu (Objekt, Teleskop), neueste zuerst. Mehrere sind
    legitim (Option „neuer Verwaltungseintrag" — z. B. Nacht 1 und Nacht 2
    getrennt entwickeln)."""
    q = select(Observation).where(Observation.user_id == user.id)
    if cat:
        q = q.where(Observation.catalog_object_id == cat.id)
    else:
        q = q.where(Observation.target_label == label, Observation.catalog_object_id.is_(None))
    q = q.where(Observation.telescope_id == telescope_id if telescope_id else Observation.telescope_id.is_(None))
    q = q.order_by(Observation.created_at.desc())
    return list(await db.scalars(q))


async def _known_filenames(db: AsyncSession, obss: list[Observation]) -> set[str]:
    """Registrierte Dateinamen über ALLE übergebenen Aufnahmen — ein Sub darf
    nie in zwei Einträgen landen (Löschen würde sonst fremde Dateien treffen)."""
    known: set[str] = set()
    for obs in obss:
        rows = await db.scalars(
            select(SubFrame.original_filename).where(SubFrame.observation_id == obs.id)
        )
        known.update(rows)
    return known


async def _create_observation(
    db: AsyncSession, user: User, cat, label: str, telescope_id
) -> Observation:
    """Legt IMMER eine neue Aufnahme an (kein Upsert) — für die Option
    „komplett neuer Verwaltungseintrag"."""
    obs = Observation(
        user_id=user.id, catalog_object_id=cat.id if cat else None,
        target_label=None if cat else label, status="geplant",
        telescope_id=telescope_id, is_new=True,
    )
    db.add(obs)
    await db.flush()
    return obs


class PreviewBody(BaseModel):
    paths: list[str]


@router.post("/preview")
async def preview(
    body: PreviewBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gruppiert die Pfadliste nach (Objekt, Gerät) und liefert Matching-Infos."""
    cat = await _catalog_map(db)
    scopes = list(await db.scalars(select(Telescope).where(Telescope.user_id == user.id)))
    scope_by_lower = {(t.name or "").strip().lower(): t for t in scopes}

    groups: dict[tuple[str, str], dict] = {}
    skipped: list[dict] = []
    for p in body.paths:
        obj, dev, name = _split_group(p)
        if PurePosixPath(name).suffix.lower() not in RAW_EXTS:
            skipped.append({"path": p, "reason": "kein FIT (.fit/.fits/.fts)"})
            continue
        parsed = asi.parse_frame_filename(name)
        g = groups.setdefault((obj, dev), {
            "object": obj, "device": dev, "files": 0,
            "filters": {}, "nights": set(), "unparsed": 0,
        })
        g["files"] += 1
        if parsed:
            fn = parsed.filter_name or "—"
            g["filters"][fn] = g["filters"].get(fn, 0) + 1
            if parsed.captured_at:
                g["nights"].add(parsed.captured_at.date().isoformat())
        else:
            g["unparsed"] += 1

    out = []
    for (obj, dev), g in sorted(groups.items()):
        match = cat.get(asi.normalize_object(obj)) if obj else None
        scope = scope_by_lower.get(dev.strip().lower()) if dev else None
        warnings = []
        if not obj:
            warnings.append("Objektname fehlt (Ordnertiefe zu gering) — bitte eintragen.")
        if not dev:
            warnings.append("Gerätename fehlt — bitte eintragen.")
        elif not scope:
            warnings.append(f"„{dev}“ ist nicht als Teleskop angelegt — Ablage unter „Unbekannt“.")
        if g["unparsed"]:
            warnings.append(f"{g['unparsed']} Datei(en) ohne ASIAir-Namensschema (werden als Light ohne Metadaten importiert).")
        # Existiert schon ein Verwaltungseintrag? (→ UI: „ergänzen" vs.
        # Häkchen „als neuen Eintrag importieren")
        obss = await _matching_observations(
            db, user, match, match.ident if match else obj, scope.id if scope else None
        ) if obj else []
        existing_subs = len(await _known_filenames(db, obss)) if obss else 0
        out.append({
            "object": obj, "device": dev, "files": g["files"],
            "matched_ident": match.ident if match else None,
            "matched_name": match.name if match else None,
            "matched_telescope": scope.name if scope else None,
            "filters": [{"filter": k, "subs": v} for k, v in sorted(g["filters"].items())],
            "nights": len(g["nights"]),
            "entry_exists": len(obss) > 0,
            "entry_count": len(obss),
            "existing_subs": existing_subs,
            "warnings": warnings,
        })
    return {"groups": out, "skipped": skipped}


class NewObservationBody(BaseModel):
    object_name: str
    device_name: str = ""


@router.post("/observation")
async def create_observation(
    body: NewObservationBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legt explizit einen NEUEN Verwaltungseintrag an (auch wenn zu
    Objekt+Gerät schon einer existiert) — z. B. um Nacht 2 komplett
    eigenständig zu entwickeln. Die folgenden /file-Uploads referenzieren
    ihn per observation_id."""
    obj_label = body.object_name.strip()
    if not obj_label:
        raise HTTPException(400, "object_name fehlt")
    cat = (await _catalog_map(db)).get(asi.normalize_object(obj_label))
    scope = await _telescope_by_name(db, user, body.device_name)
    obs = await _create_observation(
        db, user, cat, cat.ident if cat else obj_label, scope.id if scope else None
    )
    await db.commit()
    return {"observation_id": str(obs.id)}


class ScanBody(BaseModel):
    dry_run: bool = True
    # Gruppen-Schlüssel "Objekt|Gerät", die als KOMPLETT NEUER Eintrag
    # registriert werden sollen (statt den bestehenden zu ergänzen).
    new_entries: list[str] = []


@router.post("/scan")
async def scan_archive(
    body: ScanBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scannt den RAW-Baum des NAS-Archivs (<RAW>/<Objekt>/<Gerät>/*.fit) und
    registriert Bestandsdateien OHNE sie zu kopieren — für Fotos, die schon
    auf dem NAS liegen. dry_run=true liefert nur die Vorschau."""
    import asyncio

    storage = archive.get_storage(user)
    raw_folder = archive.folder_name(user, "RAW")
    cat = await _catalog_map(db)
    scopes = list(await db.scalars(select(Telescope).where(Telescope.user_id == user.id)))
    scope_by_lower = {(t.name or "").strip().lower(): t for t in scopes}
    force_new = set(body.new_entries)

    try:
        objects = await asyncio.to_thread(storage.listsubdirs, raw_folder)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"RAW-Ordner nicht lesbar ({raw_folder}): {e}")

    groups = []
    total_new = 0
    for obj in sorted(objects):
        devices = await asyncio.to_thread(storage.listsubdirs, f"{raw_folder}/{obj}")
        for dev in sorted(devices):
            rel_dir = f"{raw_folder}/{obj}/{dev}"
            names = [
                n for n in await asyncio.to_thread(storage.listdir, rel_dir)
                if PurePosixPath(n).suffix.lower() in RAW_EXTS
            ]
            if not names:
                continue
            match = cat.get(asi.normalize_object(obj))
            scope = scope_by_lower.get(dev.strip().lower())
            warnings = []
            if not scope:
                warnings.append(f"„{dev}“ ist nicht als Teleskop angelegt.")

            # Bestehende Aufnahmen (können MEHRERE sein — Option „neuer
            # Eintrag"); 'neu' = in KEINEM davon registriert. Das verhindert,
            # dass ein Sub in zwei Einträgen landet.
            obss = await _matching_observations(
                db, user, match, match.ident if match else obj,
                scope.id if scope else None,
            )
            existing = await _known_filenames(db, obss)
            new_names = [n for n in names if PurePosixPath(n.replace("\\", "/")).name not in existing]

            registered = 0
            if not body.dry_run and new_names:
                key = f"{obj}|{dev}"
                if key in force_new or not obss:
                    target = await _create_observation(
                        db, user, match, match.ident if match else obj,
                        scope.id if scope else None,
                    )
                else:
                    target = obss[0]  # neuester Eintrag wird ergänzt
                r = await archive.register_files(db, user, target, rel_dir, new_names, source="nas")
                registered = r["added"]
                total_new += registered

            groups.append({
                "object": obj, "device": dev, "files": len(names),
                "new": len(new_names), "registered": registered,
                "entry_exists": len(obss) > 0,
                "entry_count": len(obss),
                "matched_ident": match.ident if match else None,
                "matched_name": match.name if match else None,
                "matched_telescope": scope.name if scope else None,
                "warnings": warnings,
            })

    if not body.dry_run:
        await db.commit()
    return {
        "dry_run": body.dry_run,
        "raw_folder": raw_folder,
        "groups": groups,
        "total_new": sum(g["new"] for g in groups) if body.dry_run else total_new,
    }


@router.post("/file")
async def import_file(
    file: UploadFile = File(...),
    object_name: str = Form(...),
    device_name: str = Form(default=""),
    observation_id: str = Form(default=""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Importiert genau eine Datei. Ohne observation_id wird der NEUESTE
    bestehende Eintrag zu (Objekt, Gerät) ergänzt bzw. einer angelegt; mit
    observation_id (siehe POST /observation) landet die Datei gezielt in
    diesem — für die Option „komplett neuer Verwaltungseintrag"."""
    obj_label = object_name.strip()
    if not obj_label:
        raise HTTPException(400, "object_name fehlt")

    cat = (await _catalog_map(db)).get(asi.normalize_object(obj_label))
    scope = await _telescope_by_name(db, user, device_name)

    # Duplikatschutz über ALLE Einträge zu (Objekt, Gerät): ein Sub darf nie
    # in zwei Verwaltungseinträgen registriert sein.
    matching = await _matching_observations(
        db, user, cat, cat.ident if cat else obj_label, scope.id if scope else None
    )
    filename_early = PurePosixPath((file.filename or "").replace("\\", "/")).name
    if filename_early and filename_early in await _known_filenames(db, matching):
        return {
            "file": filename_early, "status": "duplicate", "error": None,
            "observation_id": None, "dest": None,
        }

    if observation_id:
        import uuid as _uuid
        try:
            obs = await db.get(Observation, _uuid.UUID(observation_id))
        except ValueError:
            raise HTTPException(400, "Ungültige observation_id")
        if not obs or obs.user_id != user.id:
            raise HTTPException(404, "Aufnahme nicht gefunden")
    else:
        obs = matching[0] if matching else await _create_observation(
            db, user, cat, cat.ident if cat else obj_label,
            scope.id if scope else None,
        )

    filename = PurePosixPath((file.filename or "upload.fit").replace("\\", "/")).name
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
            tmp_path = tmp.name
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)
        result = await archive.import_files(
            db, user, obs, [(filename, tmp_path)], source="upload",
        )
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(500, f"Import fehlgeschlagen: {e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    first = result["results"][0] if result["results"] else {"status": "error", "error": "leer"}
    return {
        "file": filename,
        "status": first.get("status"),
        "error": first.get("error"),
        "observation_id": str(obs.id),
        "dest": result.get("dest"),
    }
