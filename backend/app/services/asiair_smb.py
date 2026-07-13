"""ASIAir-Zugriff per SMB (V2 Phase B2) — Server zieht Subs direkt.

Die ASIAir-Freigabe ist offen (Gast, kein Passwort). Wir walken die Freigabe
(+ optionalen Unterordner) rekursiv und sammeln alles, was nach dem
ASIAir-Light-Muster aussieht — robust gegenüber dem genauen Verzeichnis-Layout
der jeweiligen Firmware.

Alle Methoden sind blockierend (smbclient); Aufrufer wrappen via
``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from app.services import asiair as asi

logger = logging.getLogger("uvicorn.error")

# Marker-Datei im Wurzelverzeichnis der Freigabe → Wiedererkennung trotz
# IP-Wechsel. (Löschen unterstützt die ASIAir-Samba per Gast nicht, daher
# wird der Marker immer überschrieben, nie entfernt.)
MARKER_NAME = ".curastro-rig.json"


class AsiairError(Exception):
    pass


def _guest_session(host: str):
    import smbclient
    smbclient.ClientConfig(require_secure_negotiate=False)
    smbclient.register_session(host, username="guest", password="", require_signing=False)


def _marker_unc(host: str, share: str) -> str:
    return rf"\\{host}\{(share or '').strip('/\\')}\{MARKER_NAME}"


def write_marker(host: str, share: str, payload: dict) -> None:
    """Marker-Datei auf die Freigabe schreiben/überschreiben (blockierend)."""
    import smbclient
    _guest_session(host)
    with smbclient.open_file(_marker_unc(host, share), mode="w") as f:
        f.write(json.dumps(payload))


STD_SHARES = ["EMMC Images", "Udisk Images", "TF Images"]


def detect_share(host: str) -> str | None:
    """Passende ASIAir-Freigabe finden: bevorzugt die mit ``Autorun``-Ordner
    (dort liegen die Lights), sonst die erste auflistbare. ``None`` bei keiner."""
    import smbclient
    import smbclient.path as smbpath
    try:
        _guest_session(host)
    except Exception:  # noqa: BLE001
        return None
    for sh in STD_SHARES:
        try:
            if smbpath.exists(rf"\\{host}\{sh}\Autorun"):
                return sh
        except Exception:  # noqa: BLE001
            continue
    for sh in STD_SHARES:
        try:
            smbclient.listdir(rf"\\{host}\{sh}")
            return sh
        except Exception:  # noqa: BLE001
            continue
    return None


def read_marker(host: str, share: str) -> dict | None:
    """Marker-Datei lesen → dict oder None (blockierend, fehlertolerant)."""
    import smbclient
    try:
        _guest_session(host)
        with smbclient.open_file(_marker_unc(host, share), mode="r") as f:
            data = f.read()
        return json.loads(data) if data and data.strip() and data.strip() != "{}" else None
    except Exception:  # noqa: BLE001
        return None


class AsiairClient:
    def __init__(self, host: str, share: str | None, base: str | None = "",
                 user: str = "", password: str = ""):
        self.host = (host or "").strip()
        self.share = (share or "").strip().strip("/\\")
        self.base = (base or "").strip().strip("/\\")
        # ASIAir-Samba erlaubt Gast — Default „guest", kein Passwort.
        self.user = user or "guest"
        self.password = password or ""
        if not self.host:
            raise AsiairError("ASIAir-Host/IP fehlt.")
        if not self.share:
            raise AsiairError("ASIAir-Freigabe (Share) fehlt — z. B. 'EMMC Images'.")

    def _connect(self):
        import smbclient
        # Gast-Session: die ASIAir verlangt KEIN Signing/keine Verschlüsselung;
        # smbprotocol erzwingt beides per Default. Für Gast deaktivieren:
        #  - require_signing=False (sonst „guest does not support signing")
        #  - require_secure_negotiate=False (Negotiate-Verify braucht Signing-Key)
        # Vertretbar im vertrauten LAN.
        smbclient.ClientConfig(require_secure_negotiate=False)
        smbclient.register_session(
            self.host, username=self.user, password=self.password, require_signing=False
        )

    def _root_unc(self) -> str:
        unc = rf"\\{self.host}\{self.share}"
        if self.base:
            unc += "\\" + self.base.replace("/", "\\")
        return unc

    def scan(self, max_files: int = 8000, max_depth: int = 10) -> list[dict]:
        """Durchsucht die Freigabe REKURSIV und liefert Light-Subs:
        {path, name, parsed}.

        Bewusst eigene Rekursion (statt smbclient.walk): walk überspringt
        Unterverzeichnisse still, wenn deren Auflistung scheitert — dann würde
        nur die oberste Ebene geprüft. Hier wird jedes Verzeichnis explizit
        betreten, Fehler je Ordner werden geloggt (nicht abgebrochen), und die
        Tiefe ist begrenzt (Loop-Schutz)."""
        import smbclient
        root = self._root_unc()
        found: list[dict] = []
        scanned_dirs = 0
        try:
            self._connect()
        except Exception as e:  # noqa: BLE001
            raise AsiairError(f"Verbindung zur ASIAir fehlgeschlagen: {e}")

        # Iterativer Tiefendurchlauf (Stack), damit ein einzelner unlesbarer
        # Unterordner nicht den ganzen Scan kippt. scandir liefert is_dir()
        # aus der Verzeichnis-Enumeration (kein Extra-Roundtrip pro Datei).
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            path, depth = stack.pop()
            scanned_dirs += 1
            try:
                entries = list(smbclient.scandir(path))
            except Exception as e:  # noqa: BLE001
                logger.warning("ASIAir-Scan: Verzeichnis nicht lesbar — %s: %s", path, e)
                continue
            for ent in entries:
                name = ent.name
                if name in (".", ".."):
                    continue
                child = path.rstrip("\\") + "\\" + name
                try:
                    is_dir = ent.is_dir()
                except Exception:  # noqa: BLE001
                    is_dir = False
                if is_dir:
                    if depth < max_depth:
                        stack.append((child, depth + 1))
                    continue
                parsed = asi.parse_frame_filename(name)
                if parsed and parsed.is_light:
                    found.append({"path": child, "name": name, "parsed": parsed})
                    if len(found) >= max_files:
                        logger.info("ASIAir-Scan: Limit %d erreicht (%d Ordner durchsucht)", max_files, scanned_dirs)
                        return found
        logger.info("ASIAir-Scan: %d Light-Sub(s) in %d Ordner(n) gefunden", len(found), scanned_dirs)
        return found

    def read_to_temp(self, path: str, tmpdir: str) -> tuple[str, int]:
        import smbclient
        self._connect()
        os.makedirs(tmpdir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=tmpdir, suffix=".fit")
        os.close(fd)
        size = 0
        with smbclient.open_file(path, mode="rb") as fsrc, open(tmp, "wb") as fdst:
            while chunk := fsrc.read(1024 * 1024):
                fdst.write(chunk)
                size += len(chunk)
        return tmp, size

    def delete(self, path: str) -> None:
        import smbclient
        self._connect()
        smbclient.remove(path)
