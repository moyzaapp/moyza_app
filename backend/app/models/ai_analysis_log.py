from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Numeric, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class AIAnalysisLog(Base):
    """
    Registro de auditoría para análisis de IA generados por OpenAI.

    Permite:
    - Tracking de costos (tokens usados)
    - Debugging (prompts y respuestas completas)
    - Análisis de calidad
    - Compliance y auditoría
    - Optimización de prompts
    """

    __tablename__ = "ai_analysis_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Relación con la propiedad analizada
    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False,
        index=True
    )

    # Relación con el reporte (si aplica)
    report_id = Column(
        Integer,
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Tipo de análisis: "valuation" o "observations"
    analysis_type = Column(
        String(50),
        nullable=False,
        index=True
    )

    # Información del modelo usado
    model_name = Column(
        String(100),
        nullable=False
    )

    # Parámetros del modelo
    temperature = Column(
        Numeric(3, 2),
        nullable=True
    )

    max_tokens = Column(
        Integer,
        nullable=True
    )

    # Prompt enviado a OpenAI (para debugging)
    prompt = Column(
        Text,
        nullable=True
    )

    # Respuesta completa de OpenAI (JSON)
    response = Column(
        Text,
        nullable=False
    )

    # Métricas de uso (tokens)
    prompt_tokens = Column(
        Integer,
        nullable=True
    )

    completion_tokens = Column(
        Integer,
        nullable=True
    )

    total_tokens = Column(
        Integer,
        nullable=True
    )

    # Costo estimado en USD
    estimated_cost = Column(
        Numeric(10, 6),
        nullable=True
    )

    # Tiempo de respuesta (segundos)
    response_time_seconds = Column(
        Numeric(10, 3),
        nullable=True
    )

    # Estado de la llamada
    status = Column(
        String(50),
        nullable=False,
        default="success"  # success, error, timeout
    )

    # Mensaje de error (si aplica)
    error_message = Column(
        Text,
        nullable=True
    )

    # Indica si este análisis fue usado en un reporte
    used_in_report = Column(
        Boolean,
        default=True,
        nullable=False
    )

    # Metadata adicional (JSON string)
    extra_metadata = Column(
        Text,
        nullable=True
    )

    # Timestamps
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    # Relationships
    property = relationship("Property")
    report = relationship("Report")

    def __repr__(self):
        return (
            f"<AIAnalysisLog(id={self.id}, "
            f"property_id={self.property_id}, "
            f"type={self.analysis_type}, "
            f"model={self.model_name}, "
            f"tokens={self.total_tokens}, "
            f"cost=${self.estimated_cost})>"
        )
