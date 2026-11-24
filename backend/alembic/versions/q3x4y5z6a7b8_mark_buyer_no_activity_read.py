"""mark «Comprador sin actividad» notifications read (solo datos)

PLAN_SIN_ACTIVIDAD_AGENTES.md D3 (§3.5): la variante «Sin actividad» de la
regla R1 (hubo gestión y luego 48 h hábiles sin otro seguimiento) deja de
avisar a los agentes; solo el admin la sigue viendo en el listado y el detalle
de la alerta. Los avisos `buyer_no_action` con título «Comprador sin
actividad · …» que sigan sin leer se marcan leídos para que dejen de contar en
la campana; no se borran y `cleanup_read` los eliminará a los 90 días. Los
«Comprador sin gestionar» no se tocan.

Sin cambios de esquema. Downgrade: no hace nada (no se puede saber cuáles
estaban sin leer y no tiene sentido volver a avisar de una variante retirada).

Revision ID: q3x4y5z6a7b8
Revises: p2w3x4y5z6a7
Create Date: 2026-11-23 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'q3x4y5z6a7b8'
down_revision = 'p2w3x4y5z6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE notifications SET read_at = (now() AT TIME ZONE 'UTC') "
        "WHERE kind = 'buyer_no_action' AND read_at IS NULL "
        "AND title LIKE 'Comprador sin actividad%'"
    )


def downgrade() -> None:
    pass
