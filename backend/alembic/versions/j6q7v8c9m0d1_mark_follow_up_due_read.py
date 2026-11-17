"""mark follow_up_due notifications read (solo datos)

PLAN_RUIDO_CAMPANA.md D3: el aviso diario «Seguimiento vencido / para hoy»
(`follow_up_due`) se retira: en producción el 97 % quedaba sin leer y
"Hoy y pendiente" del Inicio ya muestra las próximas acciones vencidas. Las
notificaciones de ese tipo que sigan sin leer se marcan leídas para que dejen
de contar en la campana; no se borran (el tipo se conserva en
`NotificationKind.STYLES` para pintar el historial) y `cleanup_read` las
eliminará a los 90 días.

Sin cambios de esquema. Downgrade: no hace nada (no se puede saber cuáles
estaban sin leer y no tiene sentido volver a avisar de un tipo retirado).

Revision ID: j6q7v8c9m0d1
Revises: i5p6u7b8l9c0
Create Date: 2026-11-17 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'j6q7v8c9m0d1'
down_revision = 'i5p6u7b8l9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE notifications SET read_at = (now() AT TIME ZONE 'UTC') "
        "WHERE kind = 'follow_up_due' AND read_at IS NULL"
    )


def downgrade() -> None:
    pass
