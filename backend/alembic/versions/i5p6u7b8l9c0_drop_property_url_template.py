"""el enlace público sale solo de properties.public_url

PLAN_ENVIO_PROPIEDAD_COMPRADOR.md (cambio del 2026-11-13): la ETL del CRM ya
escribe el enlace de cada inmueble en `properties.public_url`, así que la app
deja de calcularlo con la plantilla de la empresa (la de MOYZA fallaba en
parte de los inmuebles: unos llevan el sufijo "00" y otros no). Se elimina
`companies.property_url_template`.

El downgrade recrea la columna con las dos plantillas que había.

Revision ID: i5p6u7b8l9c0
Revises: h4m5o6e7s8l9
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'i5p6u7b8l9c0'
down_revision = 'h4m5o6e7s8l9'
branch_labels = None
depends_on = None

TEMPLATES = {
    "MOYZA": "https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349{referencia}00",
    "MOES": "https://www.inmoespremium.com/inmueble.php?ID=7533675336{referencia}",
}


def upgrade() -> None:
    op.drop_column('companies', 'property_url_template')


def downgrade() -> None:
    op.add_column('companies', sa.Column('property_url_template', sa.String(length=500), nullable=True))
    for code, template in TEMPLATES.items():
        op.execute(
            sa.text("UPDATE companies SET property_url_template = :template WHERE code = :code")
            .bindparams(template=template, code=code)
        )
