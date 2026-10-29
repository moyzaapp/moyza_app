import builtins
import re
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import Boolean
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class PropertyVisit(Base):

    __tablename__ = "property_visits"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False
    )

    visitor_name = Column(
        String,
        nullable=False
    )

    dni = Column(
        String,
        nullable=True
    )

    phone = Column(
        String,
        nullable=True
    )

    email = Column(
        String,
        nullable=True
    )

    purchase_fees = Column(
        String,
        nullable=True
    )

    interest_level = Column(
        Integer,
        nullable=True
    )

    price_feedback = Column(
        String,
        nullable=True
    )

    location_feedback = Column(
        String,
        nullable=True
    )

    condition_feedback = Column(
        String,
        nullable=True
    )

    lighting_feedback = Column(
        String,
        nullable=True
    )

    elevator_feedback = Column(
        String,
        nullable=True
    )

    garage_feedback = Column(
        String,
        nullable=True
    )

    notes = Column(
        Text,
        nullable=True
    )

    visit_sheet_filename = Column(
        String,
        nullable=True
    )

    visit_sheet_filepath = Column(
        String,
        nullable=True
    )

    visit_sheet_generated_at = Column(
        DateTime,
        nullable=True
    )

    visit_sheet_sent_to = Column(
        String,
        nullable=True
    )

    # Campos de consentimiento de datos (RGPD)
    data_consent_accepted = Column(
        Boolean,
        default=False,
        nullable=False
    )

    data_consent_accepted_at = Column(
        DateTime,
        nullable=True
    )

    data_consent_ip = Column(
        String,
        nullable=True
    )

    data_consent_user_agent = Column(
        String,
        nullable=True
    )

    # Campos de firma digital
    signature_filename = Column(
        String,
        nullable=True
    )

    signature_filepath = Column(
        String,
        nullable=True
    )

    signature_captured_at = Column(
        DateTime,
        nullable=True
    )

    signature_ip = Column(
        String,
        nullable=True
    )

    # Estado del proceso de visita
    # Estados: 'draft', 'preview', 'signed', 'completed'
    visit_status = Column(
        String,
        default='completed',
        nullable=False
    )

    # Audit trail completo en formato JSON
    audit_trail = Column(
        JSON,
        nullable=True
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )

    # Agente que realizó la visita (acompañó al cliente). Figura y firma en
    # la ficha. Puede ser NULL en visitas antiguas sin atribución.
    agent_id = Column(
        Integer,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Segundo agente cuando la visita se hizo entre dos. Opcional.
    companion_agent_id = Column(
        Integer,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Confirmación de las firmas registradas de los dos agentes en una visita
    # conjunta (PLAN_FIRMA_AGENTES_VISITA.md): quién la confirmó en la
    # tablet, cuándo y desde qué IP. NULL en visitas individuales.
    agent_signatures_confirmed_at = Column(
        DateTime,
        nullable=True
    )

    agent_signatures_confirmed_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    agent_signatures_confirmed_ip = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    # Relaciones
    property = relationship("Property", back_populates="visits")
    # `foreign_keys` explícito: property_visits tiene dos FK a users.
    creator = relationship("User", foreign_keys=[created_by])
    agent_signatures_confirmer = relationship(
        "User",
        foreign_keys=[agent_signatures_confirmed_by]
    )
    agent = relationship(
        "Agent",
        foreign_keys=[agent_id],
        back_populates="visits_as_agent"
    )
    companion_agent = relationship(
        "Agent",
        foreign_keys=[companion_agent_id],
        back_populates="visits_as_companion"
    )
    audit_logs = relationship("VisitAuditLog", back_populates="visit", cascade="all, delete-orphan")
    otp_verifications = relationship("VisitOTPVerification", back_populates="visit", cascade="all, delete-orphan")
    whatsapp_logs = relationship("VisitWhatsappLog", back_populates="visit", cascade="all, delete-orphan")

    @staticmethod
    def clean_purchase_fees(value):
        """Deja el importe o el porcentaje: quita '€', '+ IVA' y espacios que algunos
        agentes escriben y conserva el '%' ("2 % + IVA" -> "2%").

        Se guarda así en `purchase_fees`: "2500" son euros (también los valores
        antiguos, que eran solo dígitos) y "2%" un porcentaje
        (PLAN_CEDER_COMPRADORES.md §2).
        """
        if not value:
            return ""
        return re.sub(r"(?i)iva|€|\+|\s", "", value)

    # builtins.property porque el atributo 'property' (relación) tapa al decorador
    @builtins.property
    def purchase_fees_unit(self):
        """Unidad de los honorarios para el selector del formulario: '€' o '%'."""
        return "%" if self.clean_purchase_fees(self.purchase_fees).endswith("%") else "€"

    @builtins.property
    def purchase_fees_amount(self):
        """Honorarios sin signo para el input del formulario ("2500", "2")."""
        return self.clean_purchase_fees(self.purchase_fees).rstrip("%")

    @builtins.property
    def purchase_fees_display(self):
        """Honorarios para el informe: '€2500 + IVA' o '2% + IVA'."""
        amount = self.purchase_fees_amount
        if not amount:
            return None
        if self.purchase_fees_unit == "%":
            return f"{amount}% + IVA"
        return f"€{amount} + IVA"

    @builtins.property
    def signing_agent(self):
        """Agente que figura y firma en la ficha.

        El que realizó la visita; en visitas antiguas sin atribución, el
        agente captador de la propiedad.
        """
        if self.agent is not None:
            return self.agent
        return self.property.agent if self.property is not None else None

    @builtins.property
    def participating_agent_ids(self):
        """Ids de los agentes que participaron (principal y acompañante)."""
        return {
            agent_id
            for agent_id in (self.agent_id, self.companion_agent_id)
            if agent_id is not None
        }

    # ------------------------------------------------------------------
    # Firmas de los agentes (PLAN_FIRMA_AGENTES_VISITA.md, modalidad A)
    # ------------------------------------------------------------------

    @builtins.property
    def requires_agent_confirmation(self):
        """Visita conjunta: los agentes confirman sus firmas registradas."""
        return self.companion_agent_id is not None

    @builtins.property
    def agents_missing_signature(self):
        """Agentes de la visita (principal y acompañante) sin firma registrada en disco."""
        agents = [self.signing_agent]
        if self.companion_agent_id is not None:
            agents.append(self.companion_agent)
        return [
            agent for agent in agents
            if agent is not None and not agent.has_signature_file
        ]

    @builtins.property
    def agent_signatures_confirmed(self):
        return self.agent_signatures_confirmed_at is not None

    @builtins.property
    def can_finalize_agents(self):
        """Los agentes no bloquean el cierre: visita individual o firmas confirmadas."""
        return not self.requires_agent_confirmation or self.agent_signatures_confirmed
