"""OIDC-Provider-Konfiguration aus der ``.env``.

Vereinfachte Variante des curai-Pendants: kein DB-/Admin-Store, keine
Fernet-Verschlüsselung. Die Config wird einmalig aus den ``OIDC_*``-
Umgebungsvariablen gebaut. Reicht für eine Single-User-App, die genau
eine Keycloak-Instanz anbindet.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings

settings = get_settings()


@dataclass
class OidcProviderConfig:
    enabled: bool
    discovery_url: str | None
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    scopes: str
    groups_claim: str
    provider_label: str

    @property
    def is_usable(self) -> bool:
        return bool(
            self.enabled
            and self.discovery_url
            and self.client_id
            and self.redirect_uri
        )

    @property
    def well_known_url(self) -> str:
        """Normalisiert die Discovery-URL auf den well-known-Endpunkt.

        Keycloak wird i.d.R. als Realm-Basis konfiguriert
        (``https://host/realms/foo``). Wer die volle well-known-URL
        einträgt, wird nicht doppelt ergänzt."""
        url = (self.discovery_url or "").rstrip("/")
        suffix = "/.well-known/openid-configuration"
        return url if url.endswith(suffix) else url + suffix


def load_config() -> OidcProviderConfig:
    return OidcProviderConfig(
        enabled=bool(settings.oidc_discovery_url and settings.oidc_client_id),
        discovery_url=settings.oidc_discovery_url,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
        scopes=settings.oidc_scopes,
        groups_claim=settings.oidc_groups_claim,
        provider_label=settings.oidc_provider_label,
    )
