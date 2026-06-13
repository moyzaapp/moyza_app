from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class ReportJobLog(Base):
    """
    Registro de auditoría para las ejecuciones del job de reportes automáticos.
    Permite trazabilidad, observabilidad y reintentos.
    """

    __tablename__ = "report_job_logs"

    id = Column(Integer, primary_key=True, index=True)

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False,
        index=True
    )

    report_id = Column(
        Integer,
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True
    )

    job_run_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    status = Column(
        String,
        nullable=False,
        default="pending"
    )

    stage = Column(
        String,
        nullable=True
    )

    error_message = Column(
        Text,
        nullable=True
    )

    retry_count = Column(
        Integer,
        default=0,
        nullable=False
    )

    duration_seconds = Column(
        Numeric(10, 2),
        nullable=True
    )

    metadatas = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    property = relationship("Property")
    report = relationship("Report")
