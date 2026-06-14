"""Auth-Routen – lokaler Login, Refresh, OIDC (Keycloak)."""

import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import (
    create_access_token,
    create_oidc_state_token,
    create_refresh_token,
    decode_token,
    verify_oidc_state_token,
    verify_password,
)
from app.database import get_db
from app.models.user import AuthMethod, User, UserRole
from app.schemas.auth import (
    LoginRequest,
    OidcExchangeRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services import oidc_config as oidc_cfg
from app.services.oidc_service import OidcError, OidcSvc

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(
        request.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Benutzername oder Passwort",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Konto ist deaktiviert"
        )

    user.last_login = datetime.now(timezone.utc)
    token_data = {"sub": str(user.id), "role": user.role.value}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiges Refresh-Token"
        )
    user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User nicht gefunden"
        )
    token_data = {"sub": str(user.id), "role": user.role.value}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/oidc/config")
async def oidc_public_config():
    """Öffentliche OIDC-Sichtbarkeit fürs Login-UI (kein Secret)."""
    cfg = oidc_cfg.load_config()
    return {"enabled": cfg.is_usable, "label": cfg.provider_label}


@router.get("/oidc/login")
async def oidc_login():
    cfg = oidc_cfg.load_config()
    if not cfg.is_usable:
        raise HTTPException(status_code=400, detail="OIDC ist nicht konfiguriert")
    nonce = secrets.token_urlsafe(24)
    state = create_oidc_state_token(nonce)
    try:
        url = await OidcSvc.get_login_url(cfg, state=state, nonce=nonce)
    except OidcError as e:
        logger.error("OIDC login URL build failed: %s", e)
        raise HTTPException(status_code=502, detail="OIDC-Provider nicht erreichbar")
    return {"url": url}


@router.post("/oidc/token", response_model=TokenResponse)
async def oidc_token_exchange(
    request: OidcExchangeRequest, db: AsyncSession = Depends(get_db)
):
    cfg = oidc_cfg.load_config()
    if not cfg.is_usable:
        raise HTTPException(status_code=400, detail="OIDC ist nicht konfiguriert")

    # State/Nonce prüfen (CSRF + Replay).
    if not request.state:
        raise HTTPException(status_code=400, detail="Missing OIDC state")
    state_claims = verify_oidc_state_token(request.state)
    if not state_claims or not state_claims.get("nonce"):
        raise HTTPException(status_code=400, detail="Invalid OIDC state")
    expected_nonce = state_claims["nonce"]

    try:
        tokens = await OidcSvc.exchange_code(cfg, request.code)
        id_token = tokens.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail="Kein ID-Token erhalten")

        claims = await OidcSvc.decode_id_token(cfg, id_token, nonce=expected_nonce)
        subject = claims.get("sub")
        email = claims.get("email")
        username = claims.get("preferred_username") or (
            email.split("@")[0] if email else "oidc_user"
        )
        if not subject or not email:
            raise HTTPException(status_code=400, detail="OIDC-Token unvollständig")

        email_verified = claims.get("email_verified") is True

        # User finden/anlegen – primär über das stabile ``sub``.
        user = await db.scalar(select(User).where(User.oidc_subject == subject))
        if user is None and email_verified:
            candidate = await db.scalar(select(User).where(User.email == email))
            if candidate is not None:
                if candidate.auth_method == AuthMethod.OIDC:
                    user = candidate
                else:
                    # Lokalen Account nicht automatisch übernehmen (Takeover-Schutz).
                    raise HTTPException(
                        status_code=409,
                        detail="Lokales Konto mit dieser E-Mail existiert bereits.",
                    )

        if not user:
            user = User(
                username=username,
                email=email,
                oidc_subject=subject,
                auth_method=AuthMethod.OIDC,
                role=UserRole.ADMIN,  # Single-User: OIDC-User ist Admin
                is_active=True,
                settings={},
                first_name=claims.get("given_name"),
                last_name=claims.get("family_name"),
                full_name=claims.get("name"),
                last_login=datetime.now(timezone.utc),
            )
            db.add(user)
            await db.flush()
            from app.services.seed import seed_default_equipment

            await seed_default_equipment(db, user.id)
        else:
            user.oidc_subject = subject
            user.last_login = datetime.now(timezone.utc)
            if claims.get("given_name"):
                user.first_name = claims["given_name"]
            if claims.get("family_name"):
                user.last_name = claims["family_name"]
            if claims.get("name"):
                user.full_name = claims["name"]

        token_data = {"sub": str(user.id), "role": user.role.value}
        return TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OIDC Exchange Error: %s", e, exc_info=True)
        raise HTTPException(status_code=401, detail="OIDC-Authentifizierung fehlgeschlagen")
