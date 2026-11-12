"""Alta y borrado de cierres registrados a mano, de uno o de dos agentes.

PLAN_CIERRES_DOS_AGENTES.md. Un cierre compartido son dos registros de
`closings`, uno por agente, con el mismo `pair_key` y `shared_with_agent_id`
cruzado: la métrica sigue contando registros por agente (cada uno suma 1 y el
equipo, la suma), y la pantalla los trata como una sola operación. Se crean y
se borran siempre juntos, y cada cambio refresca los snapshots congelados de
los agentes afectados (`PerformanceReportService.refresh_closings_snapshot`).
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.constants import BusinessType
from app.models.agent import Agent
from app.models.closing import Closing
from app.models.property import Property
from app.services.company_scope import scope_active_agents
from app.services.company_scope import scope_properties
from app.services.performance_report_service import PerformanceReportService

MAX_AGENTS = 2


class ClosingError(ValueError):
    """Datos del cierre no válidos; el mensaje se muestra tal cual al admin."""


@dataclass
class DeletedClosing:
    """Lo que queda de un cierre borrado (los registros ya no existen)."""

    closed_on: date
    agent_ids: list

    @property
    def shared(self) -> bool:
        return len(self.agent_ids) > 1


def _refresh_snapshots(db: Session, company_id: int, agent_ids, closed_on: date) -> None:
    svc = PerformanceReportService(db, company_id)
    for agent_id in agent_ids:
        svc.refresh_closings_snapshot(agent_id, closed_on)


def create_closing(
    db: Session,
    company_id: int,
    agent_ids,
    business_type: str,
    closed_on: date,
    property_id: Optional[int] = None,
    notes: Optional[str] = None,
    created_by: Optional[int] = None,
) -> list:
    """Registra un cierre de uno o dos agentes y devuelve sus registros (Agente 1 primero).

    Los agentes deben ser distintos, activos y de la empresa; la propiedad,
    opcional, de la empresa. Con dos agentes se crean dos registros con la
    misma fecha, operación, propiedad, nota y `created_at`, el mismo
    `pair_key` y cada uno apuntando al otro. La fecha llega ya validada (no
    futura) por quien llama. Lanza `ClosingError` si algo no cuadra.
    """
    ids = [agent_id for agent_id in agent_ids if agent_id]
    if not ids:
        raise ClosingError("Elige un agente activo de la empresa")
    if len(ids) > MAX_AGENTS:
        raise ClosingError("Un cierre puede ser de dos agentes como máximo")
    if len(set(ids)) != len(ids):
        raise ClosingError("Los dos agentes del cierre deben ser distintos")

    found = {
        agent.id: agent
        for agent in scope_active_agents(db.query(Agent), company_id).filter(Agent.id.in_(ids))
    }
    if len(found) != len(ids):
        raise ClosingError("Elige un agente activo de la empresa")
    agents = [found[agent_id] for agent_id in ids]

    if not BusinessType.is_valid(business_type):
        raise ClosingError("Indica si el cierre es de Venta o de Alquiler")

    if property_id is not None:
        prop = scope_properties(db.query(Property), company_id).filter(Property.id == property_id).first()
        if prop is None:
            raise ClosingError("La propiedad no pertenece a la empresa activa")

    shared = len(agents) == 2
    pair_key = str(uuid.uuid4()) if shared else None
    created_at = datetime.utcnow()
    closings = []
    for index, agent in enumerate(agents):
        partner = agents[1 - index] if shared else None
        closings.append(Closing(
            company_id=company_id,
            agent_id=agent.id,
            shared_with_agent_id=partner.id if partner else None,
            pair_key=pair_key,
            business_type=business_type,
            closed_on=closed_on,
            property_id=property_id,
            notes=(notes or "").strip() or None,
            created_by=created_by,
            created_at=created_at,
        ))
    db.add_all(closings)
    db.commit()
    _refresh_snapshots(db, company_id, ids, closed_on)
    return closings


def delete_closing(db: Session, company_id: int, closing_id: int) -> DeletedClosing:
    """Borra un cierre de la empresa y, si es compartido, también el registro del otro agente.

    Refresca los snapshots de los agentes afectados. Lanza `ClosingError` si
    el cierre no existe en la empresa.
    """
    closing = (
        db.query(Closing)
        .filter(Closing.id == closing_id, Closing.company_id == company_id)
        .first()
    )
    if closing is None:
        raise ClosingError("Cierre no encontrado en la empresa activa")

    records = [closing]
    if closing.pair_key:
        records = (
            db.query(Closing)
            .filter(Closing.company_id == company_id, Closing.pair_key == closing.pair_key)
            .order_by(Closing.id)
            .all()
        )
    # Fecha por registro: la de la pareja es la misma, pero no se da por hecho
    affected = [(record.agent_id, record.closed_on) for record in records]
    for record in records:
        db.delete(record)
    db.commit()

    svc = PerformanceReportService(db, company_id)
    for agent_id, closed_on in affected:
        svc.refresh_closings_snapshot(agent_id, closed_on)
    return DeletedClosing(closed_on=affected[0][1], agent_ids=[agent_id for agent_id, _ in affected])
