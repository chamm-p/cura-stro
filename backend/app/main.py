"""cura-stro – FastAPI-Einstiegspunkt.

Lifespan: führt beim Start die Alembic-Migrationen aus und legt – falls
noch kein User existiert – den lokalen Default-User aus der ``.env`` an
(Single-User-Absicherung / Fallback ohne Keycloak).
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api import auth, calculator, equipment, geocode, health, images, locations, objects, observations, seeing, targets, users
from app.api import archive, asiair, mcp_config, slideshow, subframes
from app.api import settings as settings_api
from app.config import get_settings
from app.core.security import hash_password
from app.database import async_session
from app.mcp_server import mcp as mcp_server
from app.models.user import AuthMethod, User, UserRole
from app.services.catalog_seed import seed_catalog
from app.services.seed import seed_default_equipment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cura-stro")
settings = get_settings()


def _run_alembic_upgrade() -> None:
    """Synchroner Alembic-Upgrade (im Threadpool aufgerufen)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


async def _bootstrap_default_user() -> None:
    if not settings.default_user_enabled:
        return
    async with async_session() as db:
        count = await db.scalar(select(func.count()).select_from(User))
        if count and count > 0:
            return
        logger.info("🆕 Lege Default-User '%s' an", settings.default_user_username)
        user = User(
            username=settings.default_user_username,
            email=settings.default_user_email,
            password_hash=hash_password(settings.default_user_password),
            role=UserRole.ADMIN,
            auth_method=AuthMethod.LOCAL,
            settings={},
        )
        db.add(user)
        await db.flush()
        await seed_default_equipment(db, user.id)
        await db.commit()


# MCP-ASGI-App einmalig bauen (initialisiert den Session-Manager). Endpunkt
# wird unter /mcp/ bedient (Trailing Slash; /mcp leitet per 307 dorthin um).
_mcp_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.to_thread(_run_alembic_upgrade)
        logger.info("✅ Alembic-Migrationen ausgeführt")
    except Exception:
        logger.exception("❌ Alembic-Upgrade fehlgeschlagen")
        raise
    try:
        await _bootstrap_default_user()
    except Exception:
        logger.exception("⚠️ Bootstrap Default-User fehlgeschlagen")
    try:
        async with async_session() as db:
            await seed_catalog(db)
    except Exception:
        logger.exception("⚠️ Katalog-Seeding fehlgeschlagen")
    # MCP-Session-Manager mitlaufen lassen (Mount führt eigene Lifespans nicht aus).
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_server.session_manager.run())
        yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def mcp_token_guard(request: Request, call_next):
    """Schützt /mcp mit einem statischen Token-Header (wie NocoDB xc-mcp-token).
    Header: ``x-curastro-token`` oder ``Authorization: Bearer <token>``."""
    if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
        tokens = await mcp_config.valid_tokens()
        if not tokens:
            return JSONResponse({"error": "MCP deaktiviert — Token in den Einstellungen generieren."}, status_code=503)
        provided = request.headers.get("x-curastro-token")
        if not provided:
            auth_h = request.headers.get("authorization", "")
            if auth_h.startswith("Bearer "):
                provided = auth_h[7:]
        if provided not in tokens:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


app.mount("/mcp", _mcp_app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(locations.router)
app.include_router(equipment.router)
app.include_router(settings_api.router)
app.include_router(geocode.router)
app.include_router(targets.router)
app.include_router(seeing.router)
app.include_router(observations.router)
app.include_router(images.router)
app.include_router(calculator.router)
app.include_router(objects.router)
app.include_router(mcp_config.router)
app.include_router(slideshow.router)
app.include_router(asiair.router)
app.include_router(subframes.router)
app.include_router(archive.router)


@app.get("/")
async def root():
    return {"app": settings.app_name, "version": settings.app_version}
