"""
La ficha de agente sigue a su usuario (PLAN_LISTAS_AGENTES_POR_EMPRESA.md, fase A).

- Migración `l8s9x0y1z2a3`: `sync_agent_companies(conn)` iguala las empresas
  de cada ficha a las de su usuario; fichas sin usuario o con un usuario sin
  empresas no se tocan.
- Asignar una alerta de otra empresa ya no amplía la ficha, pero el usuario
  del agente sigue viendo esa empresa por la alerta (`get_allowed_companies`).

Dentro de una transacción que se deshace al terminar.

    docker exec moyza_backend python -m pytest tests/test_agent_companies_follow_user.py -q
"""
import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.constants import AlertStatus

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "l8s9x0y1z2a3_agent_companies_follow_user.py"


def _migration():
    spec = importlib.util.spec_from_file_location("mig_l8s9x0y1z2a3", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    from sqlalchemy.orm import Session
    from app.db.session import engine
    try:
        connection = engine.connect()
    except Exception as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin base de datos: {e}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def ctx(db):
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()

    def agent(key, companies, user_companies=None, email=None):
        ag = Agent(name=f"PYTEST-FICHA {key.upper()}", email=email or f"pytest.ficha.{key}@example.com",
                   company=", ".join(c.name for c in companies))
        ag.companies.extend(companies)
        db.add(ag)
        if user_companies is not None:
            user = User(email=f"pytest.ficha.{key}@example.com", full_name=key.title(),
                        hashed_password="x", is_active=True)
            user.companies.extend(user_companies)
            db.add(user)
        return ag

    agents = {
        # Ficha ampliada por una asignación: MOYZA + MOES, usuario solo MOES
        "ampliada": agent("ampliada", [moyza, moes], [moes]),
        # Ya igual que su usuario
        "igual": agent("igual", [moyza], [moyza]),
        # Usuario en las dos y ficha en una: se completa
        "corta": agent("corta", [moes], [moyza, moes]),
        # Sin usuario: no se toca
        "sin_usuario": agent("sin_usuario", [moyza, moes]),
        # Usuario sin empresas: no se toca
        "usuario_vacio": agent("usuario_vacio", [moyza, moes], []),
        # Email con mayúsculas y espacios: casa igual
        "mayusculas": agent("mayusculas", [moyza, moes], [moyza],
                            email="  PYTEST.Ficha.Mayusculas@Example.com "),
    }
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, agents=agents)


def _codes(ctx, agent):
    ctx.db.expire(agent)
    return [c.code for c in sorted(agent.companies, key=lambda c: c.id)]


def test_migracion_iguala_la_ficha_al_usuario(ctx):
    changes = _migration().sync_agent_companies(ctx.db.connection())
    mine = {c["agent_id"]: c for c in changes if c["name"].startswith("PYTEST-FICHA")}
    a = ctx.agents

    assert _codes(ctx, a["ampliada"]) == ["MOES"]
    assert a["ampliada"].company == "MOES PREMIUM"
    assert mine[a["ampliada"].id]["before"] == "MOYZA, MOES PREMIUM"
    assert mine[a["ampliada"].id]["after"] == "MOES PREMIUM"

    assert _codes(ctx, a["corta"]) == ["MOYZA", "MOES"]
    assert a["corta"].company == "MOYZA, MOES PREMIUM"
    assert _codes(ctx, a["mayusculas"]) == ["MOYZA"]

    # Sin cambio: ni se tocan ni salen en el log
    assert _codes(ctx, a["igual"]) == ["MOYZA"]
    assert _codes(ctx, a["sin_usuario"]) == ["MOYZA", "MOES"]
    assert _codes(ctx, a["usuario_vacio"]) == ["MOYZA", "MOES"]
    for key in ("igual", "sin_usuario", "usuario_vacio"):
        assert a[key].id not in mine
    assert set(mine) == {a["ampliada"].id, a["corta"].id, a["mayusculas"].id}

    # Idempotente: una segunda pasada no cambia nada de lo suyo
    again = _migration().sync_agent_companies(ctx.db.connection())
    assert not [c for c in again if c["name"].startswith("PYTEST-FICHA")]


def test_upgrade_escribe_el_log(ctx, caplog):
    module = _migration()
    module.op = SimpleNamespace(get_bind=lambda: ctx.db.connection())
    with caplog.at_level("INFO", logger="alembic.runtime.migration"):
        module.upgrade()
    assert any(
        f"Ficha de agente {ctx.agents['ampliada'].id} (PYTEST-FICHA AMPLIADA): MOYZA, MOES PREMIUM -> MOES PREMIUM"
        in record.getMessage()
        for record in caplog.records
    )


def test_asignar_no_amplia_la_ficha_y_el_usuario_ve_la_alerta(ctx):
    """Agente solo de MOES con una alerta de MOYZA: su ficha sigue en MOES y su
    usuario ve MOYZA por la alerta (para trabajarla), no por la ficha."""
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.user import User
    from app.services import alert_assignment_service as svc
    from app.web.dependencies.company import get_allowed_companies

    moes_agent = ctx.agents["ampliada"]
    _migration().sync_agent_companies(ctx.db.connection())
    ctx.db.expire_all()
    user = ctx.db.query(User).filter_by(email="pytest.ficha.ampliada@example.com").one()
    assert {c.code for c in get_allowed_companies(user, ctx.db)} == {"MOES"}

    admin = User(email="pytest.ficha.admin@example.com", full_name="Admin", hashed_password="x", is_active=True)
    prop = Property(title="PYTEST-FICHA Piso", address="Calle Test 1", city="Jaén",
                    agent_id=ctx.agents["igual"].id, company_id=ctx.moyza.id)
    ctx.db.add_all([admin, prop])
    ctx.db.flush()
    alert = PropertyAlert(property=prop, company_id=ctx.moyza.id, lead_name="PYTEST-FICHA Comprador",
                          status=AlertStatus.PENDING, created_by=admin.id, created_at=datetime(2026, 11, 18, 9))
    ctx.db.add(alert)
    result = svc.assign(ctx.db, alert, moes_agent, admin, None, is_new=True, now=datetime(2026, 11, 18, 9))

    assert not hasattr(result, "granted_company")
    assert _codes(ctx, moes_agent) == ["MOES"]
    assert {c.code for c in get_allowed_companies(user, ctx.db)} == {"MOYZA", "MOES"}
