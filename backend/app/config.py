"""cura-stro – Konfiguration (pydantic-settings).

Einfacher als der curai-Stack: Single-User-App, OIDC-Provider kommt
ausschließlich aus der ``.env`` (kein DB-/Admin-UI-Store, keine
Fernet-Verschlüsselung). Keycloak wird damit über
``OIDC_DISCOVERY_URL`` + ``OIDC_CLIENT_ID`` + ``OIDC_CLIENT_SECRET`` +
``OIDC_REDIRECT_URI`` angebunden.
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    # ─── App ───
    app_name: str = "cura-stro"
    app_version: str = "0.1.0"
    debug: bool = False
    public_base_url: str = Field(default="http://localhost:9601")
    outputs_dir: str = Field(default="/app/outputs")
    # Wurzel des verwalteten Foto-Archivs (NAS, in den Container gemountet).
    # Darunter entstehen RAW/<Objekt>/<Gerät>/ und Developer/<Objekt>/<Gerät>/.
    # In Settings pro Nutzer überschreibbar (V2-Foto-Workflow).
    archive_root: str = Field(default="/archive")

    # ─── Datenbank ───
    database_url: str | None = Field(default=None)
    postgres_db: str = Field(default="curastro")
    postgres_user: str = Field(default="curastro")
    postgres_password: str = Field(default="changeme")

    @computed_field
    @property
    def async_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@db:5432/{self.postgres_db}"
        )

    # ─── Backend / JWT ───
    backend_port: int = Field(default=8000)
    secret_key: str = Field(default="CHANGE_ME")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12
    refresh_token_expire_days: int = 30

    # ─── OIDC (generisch / Keycloak) ───
    oidc_discovery_url: str | None = Field(default=None)
    oidc_client_id: str | None = Field(default=None)
    oidc_client_secret: str | None = Field(default=None)
    oidc_redirect_uri: str | None = Field(default=None)
    oidc_scopes: str = Field(default="openid email profile")
    oidc_groups_claim: str = Field(default="groups")
    oidc_provider_label: str = Field(default="Keycloak")

    # ─── Lokaler Fallback-User (Single-User-Absicherung) ───
    # Wird beim Start angelegt, falls noch kein User existiert. So ist die
    # App auch ohne erreichbares Keycloak nutzbar.
    default_user_enabled: bool = Field(default=True)
    default_user_username: str = Field(default="astro")
    default_user_email: str = Field(default="astro@example.com")
    default_user_password: str = Field(default="changeme")

    # ─── meteoblue Seeing-Scraper (Playwright-Sidecar) ───
    seeing_scraper_url: str = Field(default="http://weather-scraper:8090")
    seeing_cache_ttl_min: int = Field(default=120)

    # ─── Vision-LLM (curai-Gateway, OpenAI-kompatibel) — liest die meteoblue-
    # Wolken-Schichten aus dem Seeing-Screenshot. Leer = deaktiviert
    # (Fallback Open-Meteo). ───
    llm_gateway_url: str = Field(default="")          # z. B. https://cura.hammann.org/v1
    llm_token: str = Field(default="")
    llm_vision_model: str = Field(default="original/Qwen3.6")
    # Tägliche Aktualisierung der meteoblue-Wolken (Hintergrund-Scheduler).
    cloud_refresh_enabled: bool = Field(default=True)
    # Feste Uhrzeit (lokale Zeit des Standorts) für den täglichen Refresh.
    cloud_refresh_hour: int = Field(default=16, ge=0, le=23)

    # ─── Watch-Folder für PixInsight-Ergebnisse (Phase C) ───
    # Überwacht Developer/<Objekt>/<Gerät>/ und hängt neue Master automatisch an.
    result_watch_enabled: bool = Field(default=True)
    result_watch_interval_min: int = Field(default=10, ge=1)

    # ─── MCP-Server (Phase 8) — Token für externen Zugriff (curai etc.) ───
    # Leer = MCP-Endpunkt deaktiviert.
    mcp_token: str = Field(default="")

    # ─── CORS ───
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="allow",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
