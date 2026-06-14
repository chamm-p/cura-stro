"""Generic-OIDC-Flow via Authlib (portiert aus curai).

OIDC-Discovery (``.well-known/openid-configuration``) + JWKS-basierte
ID-Token-Verifikation. Jeder OIDC-konforme IdP ist anbindbar (Keycloak,
Entra ID, Authentik …) ohne providerspezifischen Code.

Sicherheit: ID-Token wird gegen die Provider-JWKS signatur-verifiziert,
``iss``/``aud``/``exp`` geprüft, ``nonce`` gegen den vom Backend
ausgestellten State-Token gebunden (Replay-Schutz).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt as jose_jwt
from authlib.jose.errors import JoseError

from app.services.oidc_config import OidcProviderConfig

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, Any]] = {}
_DISCOVERY_TTL = 3600.0
_JWKS_TTL = 3600.0


class OidcError(RuntimeError):
    """OIDC-Flow-Fehler (Discovery, Token-Exchange, Verifikation)."""


async def _get_discovery(cfg: OidcProviderConfig) -> dict[str, Any]:
    url = cfg.well_known_url
    now = time.time()
    cached = _DISCOVERY_CACHE.get(url)
    if cached and cached[0] > now:
        return cached[1]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        doc = resp.json()

    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if required not in doc:
            raise OidcError(f"Discovery-Dokument fehlt '{required}' ({url})")

    _DISCOVERY_CACHE[url] = (now + _DISCOVERY_TTL, doc)
    return doc


async def _get_jwks(jwks_uri: str, *, force: bool = False):
    now = time.time()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and cached[0] > now and not force:
        return cached[1]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        jwks_data = resp.json()

    key_set = JsonWebKey.import_key_set(jwks_data)
    _JWKS_CACHE[jwks_uri] = (now + _JWKS_TTL, key_set)
    return key_set


class OidcSvc:
    """Stateless OIDC-Helper; bekommt die aufgelöste Config übergeben."""

    @classmethod
    async def get_login_url(
        cls, cfg: OidcProviderConfig, *, state: str, nonce: str
    ) -> str:
        if not cfg.is_usable:
            raise OidcError("OIDC ist nicht konfiguriert")
        doc = await _get_discovery(cfg)
        params = {
            "client_id": cfg.client_id,
            "response_type": "code",
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scopes,
            "state": state,
            "nonce": nonce,
        }
        return f"{doc['authorization_endpoint']}?{urlencode(params)}"

    @classmethod
    async def exchange_code(cls, cfg: OidcProviderConfig, code: str) -> dict[str, Any]:
        if not cfg.is_usable:
            raise OidcError("OIDC ist nicht konfiguriert")
        doc = await _get_discovery(cfg)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "client_id": cfg.client_id,
        }
        if cfg.client_secret:
            data["client_secret"] = cfg.client_secret

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                doc["token_endpoint"],
                data=data,
                headers={"Accept": "application/json"},
            )
        if resp.status_code >= 400:
            logger.error(
                "OIDC token exchange fehlgeschlagen (%s): %s",
                resp.status_code,
                resp.text[:500],
            )
            raise OidcError(f"Token-Exchange fehlgeschlagen ({resp.status_code})")
        return resp.json()

    @classmethod
    async def decode_id_token(
        cls,
        cfg: OidcProviderConfig,
        id_token: str,
        *,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        doc = await _get_discovery(cfg)
        jwks_uri = doc["jwks_uri"]

        claims_options = {
            "iss": {"essential": True, "value": doc["issuer"]},
            "aud": {"essential": True, "value": cfg.client_id},
            "exp": {"essential": True},
        }
        if nonce is not None:
            claims_options["nonce"] = {"essential": True, "value": nonce}

        async def _verify(force_jwks: bool):
            key_set = await _get_jwks(jwks_uri, force=force_jwks)
            claims = jose_jwt.decode(id_token, key_set, claims_options=claims_options)
            claims.validate()
            return dict(claims)

        try:
            return await _verify(force_jwks=False)
        except JoseError as e:
            logger.info("ID-Token-Verifikation 1. Versuch fehlgeschlagen (%s) — JWKS refetch", e)
            try:
                return await _verify(force_jwks=True)
            except JoseError as e2:
                logger.error("ID-Token-Verifikation endgültig fehlgeschlagen: %s", e2)
                raise OidcError("ID-Token-Verifikation fehlgeschlagen") from e2
