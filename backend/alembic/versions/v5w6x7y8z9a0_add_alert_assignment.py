"""add alert assignment (agente distinto del captador y reasignación)

PLAN_ASIGNACION_ALERTAS.md §2.3: columnas de rastro en property_alerts y
tabla alert_assignment_logs con el historial de asignaciones.

Backfill: assigned_at = created_at y assigned_by = created_by en todas las
alertas existentes, sin filas de historial (nunca se reasignaron). Ninguna
alerta cambia de agente, y la cola secuencial, que pasa a ordenar por
coalesce(assigned_at, created_at), conserva el mismo orden.

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-10-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v5w6x7y8z9a0'
down_revision = 'u4v5w6x7y8z9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('property_alerts', sa.Column(
        'assigned_by', sa.Integer(),
        sa.ForeignKey('users.id', name='fk_property_alerts_assigned_by', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('property_alerts', sa.Column('assigned_at', sa.DateTime(), nullable=True))
    op.add_column('property_alerts', sa.Column(
        'previous_agent_id', sa.Integer(),
        sa.ForeignKey('agents.id', name='fk_property_alerts_previous_agent_id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('property_alerts', sa.Column('assignment_reason', sa.String(), nullable=True))

    op.execute(
        "UPDATE property_alerts SET assigned_at = created_at, assigned_by = created_by "
        "WHERE assigned_at IS NULL"
    )

    op.create_table(
        'alert_assignment_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('alert_id', sa.Integer(), sa.ForeignKey('property_alerts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_agent_id', sa.Integer(), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('to_agent_id', sa.Integer(), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_alert_assignment_logs_id', 'alert_assignment_logs', ['id'])
    op.create_index('ix_alert_assignment_logs_alert_id', 'alert_assignment_logs', ['alert_id'])


def downgrade():
    op.drop_index('ix_alert_assignment_logs_alert_id', table_name='alert_assignment_logs')
    op.drop_index('ix_alert_assignment_logs_id', table_name='alert_assignment_logs')
    op.drop_table('alert_assignment_logs')

    op.drop_column('property_alerts', 'assignment_reason')
    op.drop_constraint('fk_property_alerts_previous_agent_id', 'property_alerts', type_='foreignkey')
    op.drop_column('property_alerts', 'previous_agent_id')
    op.drop_column('property_alerts', 'assigned_at')
    op.drop_constraint('fk_property_alerts_assigned_by', 'property_alerts', type_='foreignkey')
    op.drop_column('property_alerts', 'assigned_by')
