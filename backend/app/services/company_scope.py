"""Filtros de alcance por empresa (MOYZA / MOES PREMIUM).

Punto único para restringir consultas a la empresa activa. Reglas:

- `company_id` puede ser un id (`==`) o una lista / tupla / set de ids (`IN`):
  la vista unificada de los agentes (PLAN_VISTA_UNIFICADA_AGENTES.md) lee de
  todas sus empresas a la vez con `get_company_ids(request)`. Una lista vacía
  no encuentra nada. `add_to_company` / `remove_from_company` siguen siendo de
  una sola empresa (escriben).

- `properties`, `buyers` y `property_alerts` tienen `company_id` directo (las
  alertas desde PLAN_ALERTA_SIN_REFERENCIA.md: una búsqueda general puede no
  tener propiedad todavía).
- `agents` y `clients` pertenecen a N empresas (tablas de pertenencia).
- `property_visits` tiene `company_id` propio (PLAN_VISITAS_OTRA_EMPRESA.md):
  la empresa desde la que se registra, que puede no ser la de la propiedad.
  `scope_visits` filtra por esa columna (lo que la empresa gestiona y cuenta
  en "Hojas de visita"); `scope_visible_visits` añade las visitas que otras
  empresas registraron a sus propiedades (solo lectura).
- Informes y logs heredan la empresa de su propiedad.

Se usan EXISTS (`.has()` / `.any()`) en lugar de JOIN para que el filtro
se pueda añadir a cualquier consulta sin chocar con joins ya existentes.

Excepciones conscientes (lista cerrada en MULTIEMPRESA_MOYZA_MOES.md §16,
PLAN_SUGERENCIAS_MULTIEMPRESA.md): las sugerencias del perfil del comprador
(`buyer_matching.matching_properties` sin empresa), las opciones del perfil
(`geo_options`, tipos), el buscador de la Propuesta con `alert_id` y asociar
una propiedad a una alerta (`routes/alerts.py::_linkable_property`) NO pasan
por estos filtros de propiedades. No añadir más sin decisión explícita.
"""
from typing import Union

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.buyer import Buyer
from app.models.client import Client
from app.models.company import Company
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_visit import PropertyVisit
from app.models.report import Report


# Un id o varios (vista unificada)
CompanyIds = Union[int, list, tuple, set, frozenset]

_MANY = (list, tuple, set, frozenset)


def _is_many(company_id) -> bool:
    return isinstance(company_id, _MANY)


def company_match(column, company_id: CompanyIds):
    """Cláusula `column == id` o `column IN (ids)` según llegue uno o varios."""
    if _is_many(company_id):
        return column.in_(list(company_id))
    return column == company_id


def company_contains(company_id: CompanyIds, value) -> bool:
    """`value == id` o `value in ids` (comprobaciones en Python)."""
    if value is None:
        return False
    if _is_many(company_id):
        return value in company_id
    return value == company_id


# ---------------------------------------------------------------------------
# Filtros de consulta
# ---------------------------------------------------------------------------

def scope_properties(query, company_id: CompanyIds):
    return query.filter(company_match(Property.company_id, company_id))


def scope_buyers(query, company_id: CompanyIds):
    return query.filter(company_match(Buyer.company_id, company_id))


def scope_agents(query, company_id: CompanyIds):
    return query.filter(Agent.companies.any(company_match(Company.id, company_id)))


def active_agents(query):
    """Solo fichas activas (baja lógica, PLAN_BAJA_USUARIOS.md §4.2).

    Para los sitios donde un agente recibe trabajo nuevo (selectores de
    asignación, equipo del Inicio, snapshots nuevos). Listados, filtros e
    historial siguen usando `scope_agents` y ven también a los inactivos.
    """
    return query.filter(Agent.is_active.is_(True))


def scope_active_agents(query, company_id: CompanyIds):
    """Agentes activos de la empresa (PLAN_BAJA_USUARIOS.md §4.2)."""
    return active_agents(scope_agents(query, company_id))


def scope_clients(query, company_id: CompanyIds):
    return query.filter(Client.companies.any(company_match(Company.id, company_id)))


def scope_alerts(query, company_id: CompanyIds):
    # Columna propia de la alerta: incluye las búsquedas sin propiedad y evita
    # el EXISTS sobre properties
    return query.filter(company_match(PropertyAlert.company_id, company_id))


def scope_visits(query, company_id: CompanyIds):
    """Visitas registradas en la empresa (columna propia de la visita)."""
    return query.filter(company_match(PropertyVisit.company_id, company_id))


def visible_visit_clause(company_id: CompanyIds):
    """Cláusula: visitas de la empresa o a propiedades de la empresa.

    Las segundas (registradas por otra empresa a una propiedad suya) se ven
    en solo lectura (PLAN_VISITAS_OTRA_EMPRESA.md §5, decisión 2).
    """
    return or_(
        company_match(PropertyVisit.company_id, company_id),
        PropertyVisit.property.has(company_match(Property.company_id, company_id)),
    )


def scope_visible_visits(query, company_id: CompanyIds):
    """Visitas que la empresa ve: las suyas y las de otras a sus propiedades."""
    return query.filter(visible_visit_clause(company_id))


def scope_reports(query, company_id: CompanyIds):
    return query.filter(Report.property.has(company_match(Property.company_id, company_id)))


def visit_agent_clause(agent_id: int):
    """Cláusula: visitas en las que participó el agente (principal o acompañante).

    Punto único para atribuir visitas a agentes; si en el futuro una visita
    admite más de dos agentes, solo cambia esta función.
    """
    return or_(
        PropertyVisit.agent_id == agent_id,
        PropertyVisit.companion_agent_id == agent_id,
    )


def visits_for_agent(query, agent_id: int):
    """Filtra una consulta de visitas a aquellas en las que participó el agente."""
    return query.filter(visit_agent_clause(agent_id))


def property_in_company_clause(company_id: CompanyIds):
    """Cláusula reutilizable para modelos con relación `property` (logs)."""
    return company_match(Property.company_id, company_id)


# ---------------------------------------------------------------------------
# Comprobaciones sobre objetos ya cargados
# ---------------------------------------------------------------------------

def in_company(obj, company_id: CompanyIds) -> bool:
    """True si el objeto (con `companies` N:M o `company_id`) pertenece a la
    empresa o, con una lista de ids, a alguna de ellas."""
    if obj is None:
        return False

    if hasattr(obj, "company_id"):
        return company_contains(company_id, obj.company_id)

    companies = getattr(obj, "companies", None)
    if companies is not None:
        return any(company_contains(company_id, c.id) for c in companies)

    return False


def property_in_company(property_item, company_id: CompanyIds) -> bool:
    return property_item is not None and company_contains(company_id, property_item.company_id)


def child_in_company(obj, company_id: CompanyIds) -> bool:
    """Para alertas, visitas e informes.

    Alertas y visitas tienen empresa propia (la alerta puede no tener
    propiedad; la visita puede ser a una propiedad de otra empresa); los
    informes heredan la de su propiedad.
    """
    if obj is None:
        return False
    own_company_id = getattr(obj, "company_id", None)
    if own_company_id is not None:
        return company_contains(company_id, own_company_id)
    return property_in_company(getattr(obj, "property", None), company_id)


# ---------------------------------------------------------------------------
# Búsquedas por id dentro de la empresa
# ---------------------------------------------------------------------------

def get_property_in_company(db: Session, property_id: int, company_id: CompanyIds):
    return (
        scope_properties(db.query(Property), company_id)
        .filter(Property.id == property_id)
        .first()
    )


def get_buyer_in_company(db: Session, buyer_id: int, company_id: CompanyIds):
    return (
        scope_buyers(db.query(Buyer), company_id)
        .filter(Buyer.id == buyer_id)
        .first()
    )


def get_agent_in_company(db: Session, agent_id: int, company_id: CompanyIds):
    return (
        scope_agents(db.query(Agent), company_id)
        .filter(Agent.id == agent_id)
        .first()
    )


def get_client_in_company(db: Session, client_id: int, company_id: CompanyIds):
    return (
        scope_clients(db.query(Client), company_id)
        .filter(Client.id == client_id)
        .first()
    )


def get_alert_in_company(db: Session, alert_id: int, company_id: CompanyIds):
    return (
        scope_alerts(db.query(PropertyAlert), company_id)
        .filter(PropertyAlert.id == alert_id)
        .first()
    )


def get_visit_in_company(db: Session, visit_id: int, company_id: CompanyIds):
    """Visita registrada en la empresa (para gestionarla: editar, firmar...)."""
    return (
        scope_visits(db.query(PropertyVisit), company_id)
        .filter(PropertyVisit.id == visit_id)
        .first()
    )


def get_visible_visit(db: Session, visit_id: int, company_id: CompanyIds):
    """Visita de la empresa o a una propiedad suya (solo lectura: descargar)."""
    return (
        scope_visible_visits(db.query(PropertyVisit), company_id)
        .filter(PropertyVisit.id == visit_id)
        .first()
    )


def get_report_in_company(db: Session, report_id: int, company_id: CompanyIds):
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
