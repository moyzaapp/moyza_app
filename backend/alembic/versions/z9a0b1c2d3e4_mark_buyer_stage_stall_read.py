"""mark buyer_stage_stall notifications read (solo datos)

PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.4: la regla «sin avance de Primera
llamada» desaparece. Las notificaciones `buyer_stage_stall` que sigan sin leer
se marcan leídas para que dejen de contar en la campana; no se borran (el tipo
se conserva en `NotificationKind.STYLES` para pintar el historial). Las
`buyer_no_action` no se tocan.

Sin cambios de esquema. Downgrade: no hace nada (no se puede saber cuáles
estaban sin leer y no tiene sentido volver a avisar de una regla retirada).

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-10-19 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'z9a0b1c2d3e4'
down_revision = 'y8z9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE notifications SET read_at = (now() AT TIME ZONE 'UTC') "
        "WHERE kind = 'buyer_stage_stall' AND read_at IS NULL"
    )


def downgrade() -> None:
    pass
