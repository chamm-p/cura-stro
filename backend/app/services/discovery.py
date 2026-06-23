"""ASIAir-Discovery im LAN (V2 Phase B2).

Echte ASIAirs identifizieren wir über ihren **Steuerport 4400**: beim Verbinden
sendet die ASIAir sofort einen Banner
``{"Event":"Version","name":"<Gerätename>","svr_ver_string":...}``. Damit
filtern wir Nicht-ASIAirs (NAS etc.) heraus UND lesen gleich den Gerätenamen.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json

ASIAIR_PORT = 4400


async def asiair_info(ip: str, timeout: float = 1.2) -> dict | None:
    """Verbindet auf 4400, liest den Version-Banner → {ip, name, version}.
    ``None``, wenn der Port zu ist oder kein ASIAir-Banner kommt."""
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, ASIAIR_PORT), timeout)
        line = await asyncio.wait_for(reader.readline(), timeout)
        info = json.loads(line.decode(errors="ignore") or "{}")
        name = info.get("name")
        if not name:
            return None  # Port offen, aber kein ASIAir-Banner
        return {"ip": ip, "name": name, "version": info.get("svr_ver_string")}
    except Exception:  # noqa: BLE001
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.3)
            except Exception:  # noqa: BLE001
                pass


async def scan_subnet(subnet: str, timeout: float = 1.2, limit: int = 512) -> list[dict]:
    """Scannt das Subnetz nach ASIAirs (Port 4400 + Banner). Liefert
    [{ip, name, version}] — nur echte ASIAirs."""
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in list(net.hosts())[:limit]]
    found: list[dict] = []
    for i in range(0, len(hosts), 128):
        batch = hosts[i:i + 128]
        results = await asyncio.gather(*[asiair_info(h, timeout) for h in batch])
        found.extend([r for r in results if r])
    return found
