"""Speicher-Abstraktion fürs Foto-Archiv (V2).

Zwei Backends mit gleicher Schnittstelle:
- ``LocalStorage`` — lokaler Pfad / gemountetes Volume.
- ``SmbStorage``   — NAS direkt per SMB2/3 (``smbprotocol``), KEIN OS-Mount.
  Protokollversion wird automatisch ausgehandelt (kein ``vers=``-Theater).

Alle Methoden sind synchron (smbprotocol blockiert); Aufrufer wrappen sie via
``asyncio.to_thread``. Pfade sind relativ (z. B. ``RAW/M11/E127/foo.fit``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

NETWORK_FS = {"cifs", "smb3", "smb2", "nfs", "nfs4", "fuse.smbnetfs"}


def _rel_parts(rel: str) -> list[str]:
    return [p for p in rel.replace("\\", "/").split("/") if p and p not in (".", "..")]


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


class Storage:
    kind = "base"

    def display_root(self) -> str: raise NotImplementedError
    def makedirs(self, rel: str) -> None: raise NotImplementedError
    def exists(self, rel: str) -> bool: raise NotImplementedError
    def put(self, rel: str, src_local: str) -> int: raise NotImplementedError
    def fetch(self, rel: str, dest_local: str) -> None: raise NotImplementedError
    def delete(self, rel: str) -> None: raise NotImplementedError
    def listdir(self, rel: str) -> list[str]: raise NotImplementedError
    def stat(self, rel: str) -> tuple[int, float]: raise NotImplementedError  # (size, mtime)
    def full_path(self, rel: str) -> str: raise NotImplementedError
    def status(self) -> dict: raise NotImplementedError


class LocalStorage(Storage):
    kind = "local"

    def __init__(self, root: str | None):
        self.root = root or "/archive"

    def _abs(self, rel: str) -> Path:
        return Path(self.root, *_rel_parts(rel))

    def display_root(self) -> str:
        return self.root

    def makedirs(self, rel: str) -> None:
        self._abs(rel).mkdir(parents=True, exist_ok=True)

    def exists(self, rel: str) -> bool:
        return self._abs(rel).exists()

    def put(self, rel: str, src_local: str) -> int:
        dst = self._abs(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_local, dst)
        return dst.stat().st_size

    def fetch(self, rel: str, dest_local: str) -> None:
        shutil.copyfile(self._abs(rel), dest_local)

    def listdir(self, rel: str) -> list[str]:
        p = self._abs(rel)
        return [e.name for e in p.iterdir() if e.is_file()] if p.is_dir() else []

    def stat(self, rel: str) -> tuple[int, float]:
        st = self._abs(rel).stat()
        return st.st_size, st.st_mtime

    def delete(self, rel: str) -> None:
        self._abs(rel).unlink(missing_ok=True)

    def full_path(self, rel: str) -> str:
        return str(self._abs(rel))

    def status(self, raw: str = "RAW", developer: str = "Developer") -> dict:
        p = Path(self.root)
        exists = p.exists()
        mnt = _mount_for(self.root)
        fstype = mnt[1] if mnt else None
        info = {
            "mode": "local", "root": self.root, "exists": exists,
            "mountpoint": mnt[0] if mnt else None, "fstype": fstype,
            "is_network": bool(fstype and fstype.lower() in NETWORK_FS),
            "writable": False, "total_bytes": None, "free_bytes": None,
            "raw_exists": (p / raw).exists(), "developer_exists": (p / developer).exists(),
            "error": None,
        }
        if exists:
            try:
                probe = p / ".curastro_probe"
                probe.write_text("ok")
                probe.unlink()
                info["writable"] = True
            except Exception as e:  # noqa: BLE001
                info["error"] = str(e)
        try:
            du = shutil.disk_usage(self.root if exists else "/")
            info["total_bytes"], info["free_bytes"] = du.total, du.free
        except Exception:  # noqa: BLE001
            pass
        return info


class SmbStorage(Storage):
    kind = "smb"

    def __init__(self, host: str | None, share: str | None, base: str | None,
                 user: str | None, password: str | None):
        self.host = (host or "").strip()
        self.share = (share or "").strip().strip("/\\")
        self.base = (base or "").strip().strip("/\\")
        self.user = user or ""
        self.password = password or ""

    # ─── intern ───
    def _connect(self):
        import smbclient
        if not self.host or not self.share:
            raise ValueError("NAS-Host und Freigabe (Share) müssen gesetzt sein.")
        # Gast/anonym, falls kein User: leere Credentials zulassen.
        smbclient.register_session(self.host, username=self.user, password=self.password)

    def _unc(self, rel: str) -> str:
        parts: list[str] = []
        if self.base:
            parts += _rel_parts(self.base)
        parts += _rel_parts(rel)
        unc = rf"\\{self.host}\{self.share}"
        if parts:
            unc += "\\" + "\\".join(parts)
        return unc

    # ─── API ───
    def display_root(self) -> str:
        return self._unc("")

    def makedirs(self, rel: str) -> None:
        import smbclient
        self._connect()
        smbclient.makedirs(self._unc(rel), exist_ok=True)

    def exists(self, rel: str) -> bool:
        import smbclient.path as smbpath
        self._connect()
        return smbpath.exists(self._unc(rel))

    def put(self, rel: str, src_local: str) -> int:
        import smbclient
        self._connect()
        parent = "/".join(_rel_parts(rel)[:-1])
        if parent:
            smbclient.makedirs(self._unc(parent), exist_ok=True)
        size = 0
        with open(src_local, "rb") as fsrc, smbclient.open_file(self._unc(rel), mode="wb") as fdst:
            while chunk := fsrc.read(1024 * 1024):
                fdst.write(chunk)
                size += len(chunk)
        return size

    def fetch(self, rel: str, dest_local: str) -> None:
        import smbclient
        self._connect()
        with smbclient.open_file(self._unc(rel), mode="rb") as src, open(dest_local, "wb") as out:
            while chunk := src.read(1024 * 1024):
                out.write(chunk)

    def listdir(self, rel: str) -> list[str]:
        import smbclient
        import smbclient.path as smbpath
        self._connect()
        unc = self._unc(rel)
        try:
            if not smbpath.isdir(unc):
                return []
            return [n for n in smbclient.listdir(unc) if smbpath.isfile(unc + "\\" + n)]
        except Exception:  # noqa: BLE001
            return []

    def delete(self, rel: str) -> None:
        import smbclient
        self._connect()
        try:
            smbclient.remove(self._unc(rel))
        except Exception:  # noqa: BLE001
            pass

    def stat(self, rel: str) -> tuple[int, float]:
        import smbclient
        self._connect()
        st = smbclient.stat(self._unc(rel))
        return st.st_size, st.st_mtime

    def full_path(self, rel: str) -> str:
        return self._unc(rel)

    def status(self, raw: str = "RAW", developer: str = "Developer") -> dict:
        import smbclient
        import smbclient.path as smbpath
        info = {
            "mode": "smb", "root": None, "exists": False, "mountpoint": None,
            "fstype": "smb", "is_network": True, "writable": False,
            "total_bytes": None, "free_bytes": None,
            "raw_exists": False, "developer_exists": False, "error": None,
        }
        try:
            info["root"] = self.display_root()
        except Exception:  # noqa: BLE001
            info["root"] = f"\\\\{self.host}\\{self.share}"
        try:
            self._connect()
            smbclient.makedirs(self._unc(""), exist_ok=True)
            info["exists"] = True
            probe = self._unc(".curastro_probe")
            with smbclient.open_file(probe, mode="wb") as f:
                f.write(b"ok")
            smbclient.remove(probe)
            info["writable"] = True
            info["raw_exists"] = smbpath.exists(self._unc(raw))
            info["developer_exists"] = smbpath.exists(self._unc(developer))
            # Freier/gesamter Speicher des NAS-Volumes (best effort).
            try:
                vol = smbclient.stat_volume(self._unc(""))
                info["total_bytes"] = vol.total_size
                info["free_bytes"] = vol.caller_available_size
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
        return info
