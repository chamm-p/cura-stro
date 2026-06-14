"""MCP-Token-Verwaltung (Phase 8) — generierbar aus den Einstellungen.

Der Token wird in ``user.settings.mcp_token`` abgelegt (Single-User) und hat
Vorrang vor ``MCP_TOKEN`` aus der ``.env`` (Bootstrap-Fallback).
"""

import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import async_session, get_db
from app.models.user import User

router = APIRouter(prefix="/api/me/mcp", tags=["mcp"])
settings = get_settings()

HEADER_NAME = "x-curastro-token"
MCP_PATH = "/mcp/"


async def valid_tokens() -> set[str]:
    """Alle gültigen MCP-Tokens: jeder User-Token (Single-User, aber OIDC legt
    einen separaten User an) plus optional der ENV-Token. Vom Middleware genutzt."""
    out: set[str] = set()
    async with async_session() as db:
        for u in await db.scalars(select(User)):
            t = (u.settings or {}).get("mcp_token")
            if t:
                out.add(t)
    if settings.mcp_token:
        out.add(settings.mcp_token)
    return out


def _view(token: str | None) -> dict:
    return {"enabled": bool(token), "token": token, "header_name": HEADER_NAME, "path": MCP_PATH}


@router.get("")
async def get_mcp(user: User = Depends(get_current_user)):
    token = (user.settings or {}).get("mcp_token") or (settings.mcp_token or None)
    return _view(token)


@router.post("/regenerate")
async def regenerate(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    token = secrets.token_urlsafe(32)
    s = dict(user.settings or {})
    s["mcp_token"] = token
    user.settings = s
    await db.flush()
    return _view(token)


@router.delete("")
async def disable(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = dict(user.settings or {})
    s.pop("mcp_token", None)
    user.settings = s
    await db.flush()
    return _view(settings.mcp_token or None)
