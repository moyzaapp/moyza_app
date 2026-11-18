"""la ficha de agente sigue a su usuario (empresas)

PLAN_LISTAS_AGENTES_POR_EMPRESA.md, fase A. Migración solo de datos: para
cada ficha de agente cuyo email coincide con un usuario (sin distinguir
mayúsculas ni espacios), `agent_companies` pasa a ser exactamente las
empresas del usuario (`user_companies`) y `agents.company` el texto unido
por id ("MOYZA, MOES PREMIUM", mismo formato que `companies_label`).

- Usuario sin ninguna empresa: la ficha no se toca.
- Ficha sin usuario (o con más de un usuario con ese email): no se toca.
- Cada ficha que cambia se escribe en el log de Alembic (id, nombre,
  antes -> después).

Hasta ahora asignar una alerta de otra empresa añadía esa empresa a la
ficha (decisión §4-1 B de PLAN_ASIGNACION_ALERTAS.md, retirada): las listas
de agentes por empresa salían mal. El agente sigue viendo esas alertas
porque `get_allowed_companies` suma las empresas de las alertas que lleva.

Solo SQL (sin modelos de la app), para que la migración no dependa de
código que cambia. `sync_agent_companies(conn)` se prueba en
tests/test_agent_companies_follow_user.py.

Downgrade: no-op. No se puede saber qué empresas de cada ficha venían de una
asignación y cuáles se marcaron a mano; si hiciera falta, se restauran desde
la copia de seguridad previa o a mano desde la ficha del agente.

Revision ID: l8s9x0y1z2a3
Revises: k7r8w9x0y1z2
Create Date: 2026-11-18 00:00:00.000000

"""
import logging

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'l8s9x0y1z2a3'
down_revision = 'k7r8w9x0y1z2'
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _label(names: list) -> str:
    return ", ".join(names)


def sync_agent_companies(conn) -> list:
    """Iguala las empresas de cada ficha a las de su usuario. Devuelve los cambios.

    Cada cambio: {"agent_id", "name", "before", "after"} con las etiquetas
    de empresas ("MOYZA, MOES PREMIUM") antes y después.
    """
    companies = {
        row.id: row.name
        for row in conn.execute(sa.text("SELECT id, name FROM companies"))
    }

    def companies_of(table: str, column: str, owner_id: int) -> list:
        rows = conn.execute(
            sa.text(f"SELECT company_id FROM {table} WHERE {column} = :owner ORDER BY company_id"),
            {"owner": owner_id},
        )
        return [row.company_id for row in rows]

    pairs = conn.execute(sa.text(
        """
        SELECT a.id AS agent_id, a.name AS name, a.company AS company_text,
               min(u.id) AS user_id, count(u.id) AS users
        FROM agents a
        JOIN users u ON lower(trim(u.email)) = lower(trim(a.email))
        WHERE a.email IS NOT NULL AND trim(a.email) <> ''
        GROUP BY a.id, a.name, a.company
        ORDER BY a.id
        """
    )).fetchall()

    changes = []
    for pair in pairs:
        if pair.users != 1:
            logger.warning(
                "Ficha de agente %s (%s): %s usuarios con su email, no se toca",
                pair.agent_id, pair.name, pair.users,
            )
            continue
        user_ids = companies_of("user_companies", "user_id", pair.user_id)
        if not user_ids:
            continue
        agent_ids = companies_of("agent_companies", "agent_id", pair.agent_id)
        after = _label([companies[cid] for cid in user_ids])
        if agent_ids == user_ids and (pair.company_text or "") == after:
            continue

        conn.execute(
            sa.text("DELETE FROM agent_companies WHERE agent_id = :agent"),
            {"agent": pair.agent_id},
        )
        for company_id in user_ids:
            conn.execute(
                sa.text("INSERT INTO agent_companies (agent_id, company_id) VALUES (:agent, :company)"),
                {"agent": pair.agent_id, "company": company_id},
            )
        conn.execute(
            sa.text("UPDATE agents SET company = :label WHERE id = :agent"),
            {"label": after, "agent": pair.agent_id},
        )
        changes.append({
            "agent_id": pair.agent_id,
            "name": pair.name,
            "before": _label([companies[cid] for cid in agent_ids]),
            "after": after,
        })
    return changes


def upgrade() -> None:
    changes = sync_agent_companies(op.get_bind())
    for change in changes:
        message = (
            f"Ficha de agente {change['agent_id']} ({change['name']}): "
            f"{change['before'] or '(sin empresas)'} -> {change['after']}"
        )
        logger.info(message)
        print(message)
    summary = f"Fichas de agente igualadas a su usuario: {len(changes)}"
    logger.info(summary)
    print(summary)


def downgrade() -> None:
    # No-op documentado (ver cabecera): no se sabe qué empresas venían de una asignación
    pass
