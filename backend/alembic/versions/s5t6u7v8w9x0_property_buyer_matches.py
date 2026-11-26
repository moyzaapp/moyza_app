"""compradores compatibles con una propiedad nueva

PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.2: tabla
`property_buyer_matches`, una fila por propiedad y alerta que encaja con ella
(se llena al dar el OK a la revisión de la propiedad nueva). Sin backfill: las
propiedades que ya existen no se cruzan.

Downgrade: borra la tabla (se pierde el historial de cruces; los envíos al
comprador siguen en los seguimientos `PROPIEDAD_ENVIADA`).

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-11-24 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 's5t6u7v8w9x0'
down_revision = 'r4s5t6u7v8w9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'property_buyer_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(),
                  sa.ForeignKey('properties.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alert_id', sa.Integer(),
                  sa.ForeignKey('property_alerts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.Integer(),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('property_id', 'alert_id', name='uq_property_buyer_matches_property_alert'),
    )
    op.create_index('ix_property_buyer_matches_id', 'property_buyer_matches', ['id'])
    op.create_index('ix_property_buyer_matches_property_id', 'property_buyer_matches', ['property_id'])
    op.create_index('ix_property_buyer_matches_agent_id', 'property_buyer_matches', ['agent_id'])


def downgrade() -> None:
    op.drop_index('ix_property_buyer_matches_agent_id', table_name='property_buyer_matches')
    op.drop_index('ix_property_buyer_matches_property_id', table_name='property_buyer_matches')
    op.drop_index('ix_property_buyer_matches_id', table_name='property_buyer_matches')
    op.drop_table('property_buyer_matches')
