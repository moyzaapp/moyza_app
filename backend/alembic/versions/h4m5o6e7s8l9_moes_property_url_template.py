"""plantilla del enlace público de las propiedades de MOES

PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.1: MOES quedó sin plantilla porque no se
conocía su patrón. Verificado contra la web el 2026-11-13: cod_cliente 75336 +
cod_captacion 75336 + referencia, sin sufijo
(`…inmueble.php?ID=75336753361525` abre la Ref. 1525; con "00" al final da
"Inmueble no disponible").

La plantilla es solo el enlace de reserva: manda `properties.public_url`, que
irá rellenando la ETL del CRM.

Revision ID: h4m5o6e7s8l9
Revises: g3v4i5s6c7o8
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'h4m5o6e7s8l9'
down_revision = 'g3v4i5s6c7o8'
branch_labels = None
depends_on = None

MOES_TEMPLATE = "https://www.inmoespremium.com/inmueble.php?ID=7533675336{referencia}"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE companies SET property_url_template = :template "
            "WHERE code = 'MOES' AND property_url_template IS NULL"
        ).bindparams(template=MOES_TEMPLATE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE companies SET property_url_template = NULL "
            "WHERE code = 'MOES' AND property_url_template = :template"
        ).bindparams(template=MOES_TEMPLATE)
    )
