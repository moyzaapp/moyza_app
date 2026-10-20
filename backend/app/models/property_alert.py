import builtins
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import event
from sqlalchemy import text

from sqlalchemy.orm import relationship
from sqlalchemy.orm import validates

from app.core.constants import AlertOrigin
from app.db.base import Base


class PropertyAlert(Base):

    __tablename__ = "property_alerts"

    # Índices para el listado /alerts y la cola de cada agente
    # (migración w6x7y8z9a0b1_add_alert_indexes)
    __table_args__ = (
        Index("ix_property_alerts_property_id", "property_id"),
        Index("ix_property_alerts_buyer_id", "buyer_id"),
        Index("ix_property_alerts_status", "status"),
        Index("ix_property_alerts_agent_id_status", "agent_id", "status"),
        # Alcance por empresa (migración y8z9a0b1c2d3_alert_without_property)
        Index("ix_property_alerts_company_id", "company_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Opcional desde PLAN_ALERTA_SIN_REFERENCIA.md: una alerta creada sin
    # referencia (búsqueda general, `origin = 'search'`) no tiene propiedad
    # hasta que el agente asocia la que elige el comprador.
    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=True
    )

    # Empresa de la alerta. Antes se heredaba de la propiedad; ahora es propia
    # porque la propiedad puede faltar. En las alertas con propiedad coincide
    # con `property.company_id` (backfill de la migración y relleno automático
    # al crear, ver `_fill_company_id`).
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False
    )

    # 'property' (creada con referencia) o 'search' (sin referencia). Solo es
    # un dato de cómo entró el comprador (etiquetas y analítica): desde
    # PLAN_PERFIL_OBLIGATORIO.md cualquier alerta puede cambiar de propiedad.
    origin = Column(
        String,
        nullable=False,
        default=AlertOrigin.PROPERTY,
        server_default=AlertOrigin.PROPERTY
    )

    # Cuándo se asoció (o cambió) la propiedad desde la Propuesta. En una
    # alerta con referencia que nunca cambió de propiedad queda a NULL.
    property_linked_at = Column(
        DateTime,
        nullable=True
    )

    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=False
    )

    # Información del interesado
    lead_name = Column(
        String,
        nullable=False
    )

    lead_phone = Column(
        String,
        nullable=True
    )

    lead_email = Column(
        String,
        nullable=True
    )

    source = Column(
        String,
        nullable=True
    )

    # Descripción de la alerta
    alert_type = Column(
        String,
        default="LEAD_INTERES"
    )

    message = Column(
        Text,
        nullable=True
    )

    priority = Column(
        String,
        default="NORMAL"
    )

    # Estado y seguimiento
    status = Column(
        String,
        default="PENDING"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    read_at = Column(
        DateTime,
        nullable=True
    )

    completed_at = Column(
        DateTime,
        nullable=True
    )

    # Auditoría
    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    buyer_id = Column(
        Integer,
        ForeignKey("buyers.id"),
        nullable=True
    )

    business_type = Column(
        String,
        nullable=True
    )

    # Asignación (PLAN_ASIGNACION_ALERTAS.md §2.3). `agent_id` es el agente que
    # trabaja la alerta; puede no ser el captador de la propiedad. Las alertas
    # anteriores a la asignación manual tienen assigned_at = created_at y
    # assigned_by = created_by.
    assigned_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    assigned_at = Column(
        DateTime,
        nullable=True
    )

    previous_agent_id = Column(
        Integer,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True
    )

    assignment_reason = Column(
        String,
        nullable=True
    )

    # Relaciones. `property` puede ser None (búsqueda sin propiedad asociada):
    # todo acceso a `alert.property.<algo>` debe protegerse.
    property = relationship(
        "Property",
        backref="alerts"
    )

    company = relationship("Company")

    # `foreign_keys` explícito: property_alerts tiene dos FK a agents
    agent = relationship(
        "Agent",
        foreign_keys=[agent_id],
        backref="alerts"
    )

    previous_agent = relationship(
        "Agent",
        foreign_keys=[previous_agent_id]
    )

    assigned_by_user = relationship(
        "User",
        foreign_keys=[assigned_by]
    )

    assignment_logs = relationship(
        "AlertAssignmentLog",
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AlertAssignmentLog.created_at.desc(), AlertAssignmentLog.id.desc()"
    )

    buyer = relationship(
        "Buyer",
        back_populates="alerts"
    )

    follow_ups = relationship(
        "AlertFollowUp",
        back_populates="alert",
        cascade="all, delete-orphan"
    )

    # ------------------------------------------------------------------
    # Búsqueda general (PLAN_ALERTA_SIN_REFERENCIA.md)
    # ------------------------------------------------------------------

    # `builtins.property`: dentro de la clase, `property` es la relación
    @builtins.property
    def is_search(self) -> bool:
        """Alerta creada sin referencia (búsqueda general).

        Solo para etiquetas y analítica (PLAN_PERFIL_OBLIGATORIO.md): no
        decide qué pasos ni acciones tiene la alerta.
        """
        return self.origin == AlertOrigin.SEARCH

    @validates("property")
    def _sync_company_from_property(self, key, property_item):
        # Una alerta con propiedad nace en la empresa de la propiedad. No se
        # sobrescribe una empresa ya fijada: asociar una propiedad a una
        # búsqueda no cambia la empresa de la alerta (la ruta ya exige que
        # sea de la misma).
        if property_item is not None and self.company_id is None:
            self.company_id = property_item.company_id
        return property_item


@event.listens_for(PropertyAlert, "before_insert")
def _fill_company_id(mapper, connection, target):
    """Red de seguridad: alerta creada solo con `property_id` y sin empresa.

    Rellena `company_id` con la empresa de la propiedad (mismo criterio que el
    backfill de la migración), para que ningún alta antigua falle por el NOT NULL.
    """
    if target.company_id is None and target.property_id is not None:
        target.company_id = connection.execute(
            text("SELECT company_id FROM properties WHERE id = :id"),
            {"id": target.property_id},
        ).scalar()
