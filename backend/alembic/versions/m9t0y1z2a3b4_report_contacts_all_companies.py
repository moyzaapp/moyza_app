"""snapshots: contactos de alertas de cualquier empresa

PLAN_LISTAS_AGENTES_POR_EMPRESA.md, fase B. El indicador "contactos" pasa a
contar las alertas del agente de cualquier empresa (antes, solo las de la
empresa del snapshot). `agent_performance_reports.contacts_all_companies`
dice con qué regla se congeló cada snapshot: False en todos los existentes
(no se recalculan) y True en los que se congelen desde ahora. El Inicio del
agente en varias empresas lo usa para no contar dos veces el mismo contacto
al sumar sus empresas.

Revision ID: m9t0y1z2a3b4
Revises: l8s9x0y1z2a3
Create Date: 2026-11-18 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'm9t0y1z2a3b4'
down_revision = 'l8s9x0y1z2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'agent_performance_reports',
        sa.Column('contacts_all_companies', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('agent_performance_reports', 'contacts_all_companies')
