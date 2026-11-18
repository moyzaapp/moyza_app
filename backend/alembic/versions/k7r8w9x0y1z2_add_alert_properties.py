"""propiedades de interés adicionales por alerta

PLAN_ALERTA_VARIAS_PROPIEDADES.md: tabla `alert_properties` con las
propiedades que el agente marca en la Propuesta además de la de la alerta
(`property_alerts.property_id`, que sigue siendo la primera). Sin backfill: la
lista completa es la propiedad de la alerta más estas.

Revision ID: k7r8w9x0y1z2
Revises: j6q7v8c9m0d1
Create Date: 2026-11-18 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'k7r8w9x0y1z2'
down_revision = 'j6q7v8c9m0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_properties',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_id', sa.Integer(),
                  sa.ForeignKey('property_alerts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('property_id', sa.Integer(),
                  sa.ForeignKey('properties.id', ondelete='CASCADE'), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('added_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alert_id', 'property_id', name='uq_alert_properties_alert_property'),
    )
    op.create_index('ix_alert_properties_id', 'alert_properties', ['id'])
    op.create_index('ix_alert_properties_alert_id', 'alert_properties', ['alert_id'])
    op.create_index('ix_alert_properties_property_id', 'alert_properties', ['property_id'])


def downgrade() -> None:
    op.drop_index('ix_alert_properties_property_id', table_name='alert_properties')
    op.drop_index('ix_alert_properties_alert_id', table_name='alert_properties')
    op.drop_index('ix_alert_properties_id', table_name='alert_properties')
    op.drop_table('alert_properties')
