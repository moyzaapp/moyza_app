"""visitas a propiedades externas (fuera del inventario)

`property_visits.property_id` pasa a admitir NULL: una visita sin propiedad
del inventario es una visita a una propiedad externa, con sus datos escritos a
mano en las columnas `external_*` (dirección y población obligatorias en el
alta; el resto opcional). Las visitas existentes no cambian.

Revision ID: p2w3x4y5z6a7
Revises: o1v2a3b4c5d6
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'p2w3x4y5z6a7'
down_revision = 'o1v2a3b4c5d6'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('external_address', sa.String()),
    ('external_city', sa.String()),
    ('external_zone', sa.String()),
    ('external_property_type', sa.String()),
    ('external_business_type', sa.String()),
    ('external_price', sa.Numeric()),
    ('external_bedrooms', sa.SmallInteger()),
    ('external_bathrooms', sa.SmallInteger()),
    ('external_m2', sa.Numeric(10, 2)),
    ('external_contact_name', sa.String()),
    ('external_contact_phone', sa.String()),
    ('external_source', sa.String()),
    ('external_url', sa.String()),
)


def upgrade() -> None:
    op.alter_column('property_visits', 'property_id', existing_type=sa.Integer(), nullable=True)
    for name, column_type in _COLUMNS:
        op.add_column('property_visits', sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    # Las visitas externas no tienen propiedad: no pueden volver a una columna obligatoria
    op.execute("DELETE FROM property_visits WHERE property_id IS NULL")
    for name, _column_type in reversed(_COLUMNS):
        op.drop_column('property_visits', name)
    op.alter_column('property_visits', 'property_id', existing_type=sa.Integer(), nullable=False)
