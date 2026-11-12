"""enlace público de las propiedades y envío al comprador

PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.1 y §4.3:

- `companies.property_url_template`: plantilla del enlace a la ficha en la web
  de la empresa, con el marcador `{referencia}`. Se rellena para MOYZA con el
  patrón verificado contra la web (cod_cliente 98349 + cod_captacion 98349 +
  referencia + "00"); MOES queda a NULL hasta que se conozca el suyo.
- `properties.public_url`: enlace pegado a mano; manda sobre la plantilla.
- `alert_follow_ups.property_id`: propiedad enviada en los seguimientos
  informativos `PROPIEDAD_ENVIADA` (FK nullable, SET NULL si se borrara la
  propiedad).

Revision ID: e1n2v3p4r5o6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e1n2v3p4r5o6'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None

MOYZA_TEMPLATE = (
    "https://www.inmobiliariamoyza.com/recursos/nficham06.php"
    "?cod_inmueble=9834998349{referencia}00"
)


def upgrade() -> None:
    op.add_column('companies', sa.Column('property_url_template', sa.String(length=500), nullable=True))
    op.add_column('properties', sa.Column('public_url', sa.String(length=500), nullable=True))
    op.add_column('alert_follow_ups', sa.Column(
        'property_id', sa.Integer(),
        sa.ForeignKey('properties.id', name='fk_alert_follow_ups_property_id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.create_index('ix_alert_follow_ups_property_id', 'alert_follow_ups', ['property_id'])

    # Solo MOYZA; MOES se queda a NULL (patrón aún desconocido)
    op.execute(
        sa.text(
            "UPDATE companies SET property_url_template = :template "
            "WHERE code = 'MOYZA' AND property_url_template IS NULL"
        ).bindparams(template=MOYZA_TEMPLATE)
    )


def downgrade() -> None:
    op.drop_index('ix_alert_follow_ups_property_id', table_name='alert_follow_ups')
    op.drop_constraint('fk_alert_follow_ups_property_id', 'alert_follow_ups', type_='foreignkey')
    op.drop_column('alert_follow_ups', 'property_id')
    op.drop_column('properties', 'public_url')
    op.drop_column('companies', 'property_url_template')
