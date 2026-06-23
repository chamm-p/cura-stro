"""ASIAir-Zugriff per SMB (V2 Phase B2) — Server zieht Subs direkt.

Die ASIAir-Freigabe ist offen (Gast, kein Passwort). Wir walken die Freigabe
(+ optionalen Unterordner) rekursiv und sammeln alles, was nach dem
ASIAir-Light-Muster aussieht — robust gegenüber dem genauen Verzeichnis-Layout
der jeweiligen Firmware.

Alle Methoden sind blockierend (smbclient); Aufrufer wrappen via
``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import tempfile

from app.services import asiair as asi


class AsiairError(Exception):
    pass


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

    def scan(self, max_files: int = 8000) -> list[dict]:
        """Walkt die Freigabe und liefert Light-Subs: {path, name, parsed}."""
        import smbclient
        root = self._root_unc()
        found: list[dict] = []
        try:
            self._connect()
            for dirpath, _dirs, files in smbclient.walk(root):
                for fn in files:
                    parsed = asi.parse_frame_filename(fn)
                    if parsed and parsed.is_light:
                        found.append({
                            "path": dirpath.rstrip("\\") + "\\" + fn,
                            "name": fn,
                            "parsed": parsed,
                        })
                        if len(found) >= max_files:
                            return found
        except Exception as e:  # noqa: BLE001
            raise AsiairError(f"Scan fehlgeschlagen: {e}")
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
