"""Archiv-Mount-Status (V2) — Sichtbarkeit im UI: ist /archive da, beschreibbar
und ein echter NAS-Mount (cifs) oder nur ein lokales Volume?"""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.services import archive as arch

router = APIRouter(prefix="/api/archive", tags=["archive"])

# Dateisysteme, die ein „echter" Netz-Mount sind (NAS aktiv).
NETWORK_FS = {"cifs", "smb3", "smb2", "nfs", "nfs4", "fuse.smbnetfs"}


def _mount_for(path: str) -> tuple[str, str] | None:
    """Längster passender Mountpoint aus /proc/mounts → (mountpoint, fstype)."""
    real = os.path.realpath(path)
    best: tuple[str, str] | None = None
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1].replace("\\040", " ")
                if real == mp or real.startswith(mp.rstrip("/") + "/"):
                    if best is None or len(mp) > len(best[0]):
                        best = (mp, parts[2])
    except OSError:
        pass
    return best


@router.get("/status")
async def archive_status(user: User = Depends(get_current_user)):
    root = arch.effective_archive_root(user)
    p = Path(root)
    exists = p.exists()

    mnt = _mount_for(root)
    mountpoint = mnt[0] if mnt else None
    fstype = mnt[1] if mnt else None
    is_network = bool(fstype and fstype.lower() in NETWORK_FS)

    writable = False
    error: str | None = None
    if exists:
        try:
            probe = p / ".curastro_probe"
            probe.write_text("ok")
            probe.unlink()
            writable = True
        except Exception as e:  # noqa: BLE001
            error = str(e)

    total = free = None
    try:
        du = shutil.disk_usage(root if exists else "/")
        total, free = du.total, du.free
    except Exception:  # noqa: BLE001
        pass

    return {
        "root": root,
        "exists": exists,
        "writable": writable,
        "mountpoint": mountpoint,
        "fstype": fstype,
        "is_network": is_network,
        "total_bytes": total,
        "free_bytes": free,
        "raw_exists": (p / "RAW").exists(),
        "developer_exists": (p / "Developer").exists(),
        "error": error,
    }
