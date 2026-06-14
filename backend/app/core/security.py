"""Security-Utilities – Passwort-Hashing, JWT, OIDC-State-Token.

Bewusst schlank gehalten (Single-User): bcrypt direkt (ohne passlib, um
Versions-Drift zu vermeiden), python-jose für JWT. Keine Fernet-
Verschlüsselung — OIDC-Secrets kommen aus der ``.env``.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


# ─── Passwort-Hashing (bcrypt direkt) ───
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# ─── JWT ───
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.refresh_token_expire_days)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None


# ─── OIDC State/Nonce-Token (CSRF + Replay-Schutz, ohne Server-Session) ───
def create_oidc_state_token(nonce: str, expires_in_seconds: int = 600) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return jwt.encode(
        {"nonce": nonce, "exp": expire, "type": "oidc_state"},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_oidc_state_token(token: str) -> dict | None:
    payload = decode_token(token)
    if not payload or payload.get("type") != "oidc_state":
        return None
    return payload
