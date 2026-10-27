"""mark buyer notifications of alerts assigned before 2026-10-20 read (solo datos)

Decisión del 2026-10-26: los avisos de compradores («sin gestión» y «volver a
llamar») solo cuentan las alertas cuya ventana de asignación empieza el
20/10/2026 o después (`settings.BUYER_ATTENTION_SINCE`). Las notificaciones
sin leer de `buyer_no_action`, `buyer_callback_due` y `buyer_stage_stall` de
alertas anteriores se marcan leídas para que dejen de contar en la campana.
No se borra nada: ni las notificaciones ni las alertas.

El corte es el de la aplicación: 20/10/2026 a las 00:00 de Madrid, comparado
con `coalesce(assigned_at, created_at)` (UTC naive). Las notificaciones de
alertas que ya no existen no se tocan (las resuelve el job).

Sin cambios de esquema. Downgrade: no hace nada (no se puede saber cuáles
estaban sin leer).

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-10-26 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notifications AS n
           SET read_at = (now() AT TIME ZONE 'UTC')
          FROM property_alerts AS a
         WHERE n.read_at IS NULL
           AND n.kind IN ('buyer_no_action', 'buyer_callback_due', 'buyer_stage_stall')
           AND n.entity_type = 'alert'
           AND n.entity_id = a.id
           AND coalesce(a.assigned_at, a.created_at)
               < ((TIMESTAMP '2026-10-20 00:00:00' AT TIME ZONE 'Europe/Madrid') AT TIME ZONE 'UTC')
        """
    )


def downgrade() -> None:
    pass
