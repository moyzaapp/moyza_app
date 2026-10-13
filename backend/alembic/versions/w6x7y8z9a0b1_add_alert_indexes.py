"""add indexes to property_alerts and alert_follow_ups

Rendimiento de /alerts (Compradores): las búsquedas por agente, estado,
comprador y propiedad, y la carga de seguimientos por alerta, hacían
recorridos completos de tabla.

`if_not_exists` para que la migración no falle si algún índice se creó a
mano en algún entorno.

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-10-13 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'w6x7y8z9a0b1'
down_revision = 'v5w6x7y8z9a0'
branch_labels = None
depends_on = None


INDEXES = [
    ('ix_property_alerts_property_id', 'property_alerts', ['property_id']),
    ('ix_property_alerts_buyer_id', 'property_alerts', ['buyer_id']),
    ('ix_property_alerts_status', 'property_alerts', ['status']),
    ('ix_property_alerts_agent_id_status', 'property_alerts', ['agent_id', 'status']),
    ('ix_alert_follow_ups_alert_id', 'alert_follow_ups', ['alert_id']),
]


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
