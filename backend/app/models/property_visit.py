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
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.core.numbers import format_es_decimal, parse_es_decimal
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

    # Empresa de la visita: la desde la que se registra (la agencia del
    # agente), no siempre la de la propiedad (PLAN_VISITAS_OTRA_EMPRESA.md):
    # un agente de MOYZA puede visitar una propiedad de MOES PREMIUM y la
    # visita es de MOYZA (alcance, marca de la ficha y "Hojas de visita").
    # Las anteriores a la columna tienen la de la propiedad (backfill). Si
    # un alta no la fija, se rellena con la de la propiedad
    # (`_fill_company_id`).
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
        index=True
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
    company = relationship("Company")
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
        (PLAN_CEDER_COMPRADORES.md §2). Los valores nuevos se guardan
        normalizados con `normalize_purchase_fees`.
        """
        if not value:
            return ""
        return re.sub(r"(?i)iva|€|\+|\s", "", value)

    @staticmethod
    def normalize_purchase_fees(value):
        """Honorarios limpios en el formato guardado: sin separador de miles y
        con coma si hay decimales ("2.500,50" -> "2500,5"; "2,50%" -> "2,5%").
        ValueError si el número no sigue la regla española
        (PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.2)."""
        clean = PropertyVisit.clean_purchase_fees(value)
        if not clean:
            return ""
        amount = format_es_decimal(parse_es_decimal(clean.rstrip("%")), thousands=False)
        return amount + ("%" if clean.endswith("%") else "")

    # builtins.property porque el atributo 'property' (relación) tapa al decorador
    @builtins.property
    def purchase_fees_unit(self):
        """Unidad de los honorarios para el selector del formulario: '€' o '%'."""
        return "%" if self.clean_purchase_fees(self.purchase_fees).endswith("%") else "€"

    @builtins.property
    def purchase_fees_value(self):
        """Importe o porcentaje como Decimal, o None si está vacío o es un valor
        antiguo que no sigue la regla española ("1.2")."""
        raw = self.clean_purchase_fees(self.purchase_fees).rstrip("%")
        try:
            return parse_es_decimal(raw, max_decimals=6) if raw else None
        except ValueError:
            return None

    @builtins.property
    def purchase_fees_amount(self):
        """Honorarios sin signo para el input del formulario ("2500", "2,5",
        "2500,5"; sin puntos de miles para que se edite cómodo). Un valor
        antiguo no interpretable sale tal cual."""
        value = self.purchase_fees_value
        if value is None:
            return self.clean_purchase_fees(self.purchase_fees).rstrip("%")
        return format_es_decimal(value, thousands=False)

    @builtins.property
    def purchase_fees_display(self):
        """Honorarios para el informe en formato español: '2.500 € + IVA',
        '2.500,50 € + IVA' o '2,5 % + IVA'. Un valor antiguo no interpretable
        se muestra tal cual con su signo."""
        amount = self.purchase_fees_amount
        if not amount:
            return None
        unit = self.purchase_fees_unit
        value = self.purchase_fees_value
        if value is not None:
            amount = format_es_decimal(value, pad=(unit == "€"))
        return f"{amount} {unit} + IVA"

    @builtins.property
    def is_cross_company(self):
        """La propiedad es de otra empresa que la visita (visita cruzada)."""
        return (
            self.property is not None
            and self.company_id is not None
            and self.property.company_id != self.company_id
        )

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


@event.listens_for(PropertyVisit, "before_insert")
def _fill_company_id(mapper, connection, target):
    """Red de seguridad: visita creada sin empresa.

    Rellena `company_id` con la empresa de la propiedad (mismo criterio que el
    backfill de la migración), para que ningún alta que no la fije falle por
    el NOT NULL. Las rutas de alta la fijan siempre (`create_visit`).
    """
    if target.company_id is not None:
        return
    # Sin cargar la relación (estamos dentro del flush): solo si ya está
    loaded_property = target.__dict__.get("property")
    if loaded_property is not None and loaded_property.company_id is not None:
        target.company_id = loaded_property.company_id
    elif target.property_id is not None:
        target.company_id = connection.execute(
            text("SELECT company_id FROM properties WHERE id = :id"),
            {"id": target.property_id},
        ).scalar()
