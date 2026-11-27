"""alerta creada por el propio agente: fuera de su cola

PLAN_ALERTA_AGENTE_SIN_COLA.md §4.1: columna `property_alerts.self_created`
(la creó el agente que la tiene asignada). Esas alertas quedan fuera de la
cola secuencial del agente (`alert_view.get_locked_alert_ids`).

Backfill (D3): las alertas abiertas (Pendiente o En proceso) que asignó el
usuario del propio agente (usuario y agente se enlazan por email, sin
distinguir mayúsculas) y que nunca se reasignaron ni cedieron. Las que asignó
un admin no cuentan, aunque tenga ficha de agente y se la asignara a sí mismo
(misma regla que `alert_assignment_service.assign`).

Downgrade: borra la columna (las alertas vuelven a la cola normal).

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-11-27 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 't6u7v8w9x0y1'
down_revision = 's5t6u7v8w9x0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'property_alerts',
        sa.Column('self_created', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    # Valores de `constants.AlertStatus`: PENDING, IN_PROGRESS, COMPLETED, CANCELLED
    op.execute(
        """
        UPDATE property_alerts a SET self_created = true
        FROM agents g JOIN users u ON lower(u.email) = lower(g.email)
        LEFT JOIN roles r ON r.id = u.role_id
        WHERE a.agent_id = g.id AND a.assigned_by = u.id
          AND a.previous_agent_id IS NULL AND a.ceded_at IS NULL
          AND a.status IN ('PENDING', 'IN_PROGRESS')
          AND lower(coalesce(r.name, '')) <> 'admin'
        """
    )


def downgrade() -> None:
    op.drop_column('property_alerts', 'self_created')
