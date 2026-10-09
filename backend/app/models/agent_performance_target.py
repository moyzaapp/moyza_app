from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentPerformanceTarget(Base):

    __tablename__ = "agent_performance_targets"

    id = Column(Integer, primary_key=True, index=True)

    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=False
    )

    # Un agente que trabaja en las dos empresas tiene objetivos separados
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
        index=True
    )

    period_type = Column(String, nullable=False)   # WEEKLY / MONTHLY / YEARLY
    period_start = Column(DateTime, nullable=False)

    target_contactos = Column(Integer, nullable=True)
    target_bajadas = Column(Integer, nullable=True)
    target_captaciones_crm = Column(Integer, nullable=True)
    target_cierres = Column(Integer, nullable=True)
    target_hojas_visita = Column(Integer, nullable=True)

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", backref="performance_targets")
