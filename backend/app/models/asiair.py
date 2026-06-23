"""ASIAir-Geräte (V2 Phase A).

Pro Rig genau eine ASIAir → eindeutiges Teleskop. Damit weiß jeder Import,
in welchen ``<Gerät>``-Unterordner die Subs gehören, obwohl der Dateiname
das Teleskop nicht enthält. Die SMB-Freigabe ist offen (kein Passwort),
daher kein Credential-Feld; ``host`` wird manuell gesetzt oder per
Netzwerk-Discovery (Phase B) befüllt.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AsiairRig(Base):
    __tablename__ = "asiair_rigs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Anzeigename, z. B. "ASIAir ES127".
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # IP/Hostname der ASIAir im LAN (SMB). Optional bis Discovery/Eingabe.
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # SMB-Freigabe-/Unterpfad auf der ASIAir (Default wird in Phase B genutzt).
    share: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Stabile Kennung: wird als Marker-Datei (.curastro-rig.json) auf die
    # ASIAir-Freigabe geschrieben → Wiedererkennung trotz IP-Wechsel.
    marker_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Zugeordnetes Teleskop → bestimmt den <Gerät>-Ordner im Archiv.
    telescope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telescopes.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
