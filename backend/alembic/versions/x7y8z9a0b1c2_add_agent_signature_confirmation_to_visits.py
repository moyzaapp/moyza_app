"""add agent signature confirmation to property_visits

PLAN_FIRMA_AGENTES_VISITA.md §3.1: en una visita conjunta (con acompañante),
el agente logueado confirma que la ficha se firma con las firmas registradas
de los dos agentes. Se guarda quién, cuándo y desde qué IP.

Sin backfill: las visitas existentes quedan con las tres columnas a NULL.
Las ya completadas no vuelven a pasar por el flujo; una visita conjunta que
siga en 'signed' pasará por la confirmación al retomarla.

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-10-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'x7y8z9a0b1c2'
down_revision = 'w6x7y8z9a0b1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('property_visits', sa.Column('agent_signatures_confirmed_at', sa.DateTime(), nullable=True))
    op.add_column('property_visits', sa.Column(
        'agent_signatures_confirmed_by', sa.Integer(),
        sa.ForeignKey('users.id', name='fk_property_visits_agent_signatures_confirmed_by', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('property_visits', sa.Column('agent_signatures_confirmed_ip', sa.String(), nullable=True))


def downgrade():
    op.drop_column('property_visits', 'agent_signatures_confirmed_ip')
    op.drop_constraint('fk_property_visits_agent_signatures_confirmed_by', 'property_visits', type_='foreignkey')
    op.drop_column('property_visits', 'agent_signatures_confirmed_by')
    op.drop_column('property_visits', 'agent_signatures_confirmed_at')
