"""alert cession (ceder comprador a otro agente)

PLAN_CEDER_COMPRADORES.md §5.3:

- `alert_assignment_logs.kind`: tipo de cada fila del historial
  (`created` alta, `reassigned` reasignación del admin, `ceded` cesión del
  propio agente). NOT NULL con valor por defecto `reassigned`; backfill: las
  filas sin agente de origen (`from_agent_id IS NULL`) son altas.
- `property_alerts.ceded_at` y `property_alerts.ceded_by_agent_id`: última
  cesión (fecha y agente que cedió) para pintar el distintivo «Cedido» sin
  recorrer el historial. Vacías mientras la alerta no se ha cedido.

Downgrade: borra las tres columnas (se pierde el tipo de las filas del
historial y la marca de cesión; las filas y las alertas se conservan).

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('alert_assignment_logs', sa.Column(
        'kind', sa.String(length=20), nullable=False, server_default='reassigned',
    ))
    op.execute("UPDATE alert_assignment_logs SET kind = 'created' WHERE from_agent_id IS NULL")

    op.add_column('property_alerts', sa.Column('ceded_at', sa.DateTime(), nullable=True))
    op.add_column('property_alerts', sa.Column(
        'ceded_by_agent_id', sa.Integer(),
        sa.ForeignKey('agents.id', name='fk_property_alerts_ceded_by_agent_id', ondelete='SET NULL'),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_constraint('fk_property_alerts_ceded_by_agent_id', 'property_alerts', type_='foreignkey')
    op.drop_column('property_alerts', 'ceded_by_agent_id')
    op.drop_column('property_alerts', 'ceded_at')
    op.drop_column('alert_assignment_logs', 'kind')
