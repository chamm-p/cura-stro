"""Netzwerk-Discovery (V2 Phase B2) — ASIAirs (SMB) im LAN finden.

Einfacher TCP-Connect-Sweep auf Port 445 über ein Subnetz. Aus dem Container
heraus erreichbar (ausgehende Verbindungen ins LAN). Liefert offene Hosts; die
Identifikation (welcher ist die ASIAir) trifft der Nutzer per Dropdown.
"""

from __future__ import annotations

import asyncio
import ipaddress


# SMB hört auf 445 (direct host) und/oder 139 (NetBIOS) — ASIAirs teils nur 139.
SMB_PORTS = (445, 139)


async def _one(ip: str, port: int, timeout: float) -> bool:
    try:
        fut = asyncio.open_connection(ip, port)
        _reader, writer = await asyncio.wait_for(fut, timeout)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 0.3)
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


async def _check(ip: str, ports: tuple[int, ...], timeout: float) -> str | None:
    for port in ports:
        if await _one(ip, port, timeout):
            return ip
    return None


async def scan_subnet(subnet: str, ports: tuple[int, ...] = SMB_PORTS, timeout: float = 0.8, limit: int = 512) -> list[str]:
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in list(net.hosts())[:limit]]
    # In Häppchen, um nicht zu viele Sockets gleichzeitig zu öffnen.
    open_hosts: list[str] = []
    for i in range(0, len(hosts), 128):
        batch = hosts[i:i + 128]
        results = await asyncio.gather(*[_check(h, ports, timeout) for h in batch])
        open_hosts.extend([r for r in results if r])
    return open_hosts
