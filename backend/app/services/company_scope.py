"""Filtros de alcance por empresa (MOYZA / MOES PREMIUM).

Punto único para restringir consultas a la empresa activa. Reglas:

- `properties` y `buyers` tienen `company_id` directo.
- `agents` y `clients` pertenecen a N empresas (tablas de pertenencia).
- Alertas, visitas, informes y logs heredan la empresa de su propiedad.

Se usan EXISTS (`.has()` / `.any()`) en lugar de JOIN para que el filtro
se pueda añadir a cualquier consulta sin chocar con joins ya existentes.
"""
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.buyer import Buyer
from app.models.client import Client
from app.models.company import Company
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_visit import PropertyVisit
from app.models.report import Report


# ---------------------------------------------------------------------------
# Filtros de consulta
# ---------------------------------------------------------------------------

def scope_properties(query, company_id: int):
    return query.filter(Property.company_id == company_id)


def scope_buyers(query, company_id: int):
    return query.filter(Buyer.company_id == company_id)


def scope_agents(query, company_id: int):
    return query.filter(Agent.companies.any(Company.id == company_id))


def scope_clients(query, company_id: int):
    return query.filter(Client.companies.any(Company.id == company_id))


def scope_alerts(query, company_id: int):
    return query.filter(PropertyAlert.property.has(Property.company_id == company_id))


def scope_visits(query, company_id: int):
    return query.filter(PropertyVisit.property.has(Property.company_id == company_id))


def scope_reports(query, company_id: int):
    return query.filter(Report.property.has(Property.company_id == company_id))


def property_in_company_clause(company_id: int):
    """Cláusula reutilizable para modelos con relación `property` (logs)."""
    return Property.company_id == company_id


# ---------------------------------------------------------------------------
# Comprobaciones sobre objetos ya cargados
# ---------------------------------------------------------------------------

def in_company(obj, company_id: int) -> bool:
    """True si el objeto (con `companies` N:M o `company_id`) pertenece a la empresa."""
    if obj is None:
        return False

    if hasattr(obj, "company_id"):
        return obj.company_id == company_id

    companies = getattr(obj, "companies", None)
    if companies is not None:
        return any(c.id == company_id for c in companies)

    return False


def property_in_company(property_item, company_id: int) -> bool:
    return property_item is not None and property_item.company_id == company_id


def child_in_company(obj, company_id: int) -> bool:
    """Para alertas, visitas e informes: la empresa es la de su propiedad."""
    if obj is None:
        return False
    return property_in_company(getattr(obj, "property", None), company_id)


# ---------------------------------------------------------------------------
# Búsquedas por id dentro de la empresa
# ---------------------------------------------------------------------------

def get_property_in_company(db: Session, property_id: int, company_id: int):
    return (
        scope_properties(db.query(Property), company_id)
        .filter(Property.id == property_id)
        .first()
    )


def get_buyer_in_company(db: Session, buyer_id: int, company_id: int):
    return (
        scope_buyers(db.query(Buyer), company_id)
        .filter(Buyer.id == buyer_id)
        .first()
    )


def get_agent_in_company(db: Session, agent_id: int, company_id: int):
    return (
        scope_agents(db.query(Agent), company_id)
        .filter(Agent.id == agent_id)
        .first()
    )


def get_client_in_company(db: Session, client_id: int, company_id: int):
    return (
        scope_clients(db.query(Client), company_id)
        .filter(Client.id == client_id)
        .first()
    )


def get_alert_in_company(db: Session, alert_id: int, company_id: int):
    return (
        scope_alerts(db.query(PropertyAlert), company_id)
        .filter(PropertyAlert.id == alert_id)
        .first()
    )


def get_visit_in_company(db: Session, visit_id: int, company_id: int):
    return (
        scope_visits(db.query(PropertyVisit), company_id)
        .filter(PropertyVisit.id == visit_id)
        .first()
    )


def get_report_in_company(db: Session, report_id: int, company_id: int):
    return (
        scope_reports(db.query(Report), company_id)
        .filter(Report.id == report_id)
        .first()
    )


# ---------------------------------------------------------------------------
# Pertenencia N:M (agentes y clientes)
# ---------------------------------------------------------------------------

def add_to_company(db: Session, obj, company_id: int) -> bool:
    """Añade un agente o cliente a la empresa. Devuelve True si se añadió."""
    if in_company(obj, company_id):
        return False

    company = db.get(Company, company_id)
    if company is None:
        raise ValueError(f"Empresa {company_id} no existe")

    obj.companies.append(company)
    return True


def remove_from_company(db: Session, obj, company_id: int) -> bool:
    """Quita a un agente o cliente de la empresa. Devuelve True si se quitó."""
    for company in list(obj.companies):
        if company.id == company_id:
            obj.companies.remove(company)
            return True
    return False
