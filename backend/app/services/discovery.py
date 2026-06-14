"""Netzwerk-Discovery (V2 Phase B2) — ASIAirs (SMB) im LAN finden.

Einfacher TCP-Connect-Sweep auf Port 445 über ein Subnetz. Aus dem Container
heraus erreichbar (ausgehende Verbindungen ins LAN). Liefert offene Hosts; die
Identifikation (welcher ist die ASIAir) trifft der Nutzer per Dropdown.
"""

from __future__ import annotations

import asyncio
import ipaddress


async def _check(ip: str, port: int = 445, timeout: float = 0.6) -> str | None:
    try:
        fut = asyncio.open_connection(ip, port)
        _reader, writer = await asyncio.wait_for(fut, timeout)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 0.3)
        except Exception:  # noqa: BLE001
            pass
        return ip
    except Exception:  # noqa: BLE001
        return None


async def scan_subnet(subnet: str, port: int = 445, timeout: float = 0.6, limit: int = 512) -> list[str]:
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in list(net.hosts())[:limit]]
    # In Häppchen, um nicht zu viele Sockets gleichzeitig zu öffnen.
    open_hosts: list[str] = []
    for i in range(0, len(hosts), 128):
        batch = hosts[i:i + 128]
        results = await asyncio.gather(*[_check(h, port, timeout) for h in batch])
        open_hosts.extend([r for r in results if r])
    return open_hosts
