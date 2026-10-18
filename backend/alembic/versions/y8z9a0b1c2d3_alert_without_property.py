"""alert without property (búsqueda general)

PLAN_ALERTA_SIN_REFERENCIA.md: una alerta de comprador puede crearse sin
referencia (búsqueda general) y asociar la propiedad más tarde.

- `property_alerts.property_id` pasa a ser opcional.
- `property_alerts.company_id`: la empresa ya no se puede deducir siempre de
  la propiedad, así que la alerta la guarda. Backfill desde la propiedad de
  cada alerta y luego NOT NULL, con índice (alcance por empresa).
- `property_alerts.origin`: 'property' (creada con referencia) o 'search'
  (sin referencia). Las existentes quedan como 'property'.
- `property_alerts.property_linked_at`: cuándo se asoció la propiedad a una
  búsqueda.

Downgrade: si hay alertas sin propiedad, falla con un mensaje claro en vez
de borrarlas (habría que asociarles una propiedad o eliminarlas a mano).

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-10-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'y8z9a0b1c2d3'
down_revision = 'x7y8z9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    # Empresa propia de la alerta: nullable para el backfill, luego NOT NULL
    op.add_column('property_alerts', sa.Column(
        'company_id', sa.Integer(),
        sa.ForeignKey('companies.id', name='fk_property_alerts_company_id'),
        nullable=True,
    ))
    op.execute(
        "UPDATE property_alerts SET company_id = "
        "(SELECT company_id FROM properties WHERE properties.id = property_alerts.property_id)"
    )
    op.alter_column('property_alerts', 'company_id', existing_type=sa.Integer(), nullable=False)
    op.create_index('ix_property_alerts_company_id', 'property_alerts', ['company_id'])

    op.add_column('property_alerts', sa.Column(
        'origin', sa.String(), nullable=False, server_default='property',
    ))
    op.add_column('property_alerts', sa.Column('property_linked_at', sa.DateTime(), nullable=True))

    op.alter_column('property_alerts', 'property_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    # No se borran búsquedas sin propiedad: el downgrade se detiene con un aviso
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM property_alerts WHERE property_id IS NULL) THEN
                RAISE EXCEPTION 'Hay alertas sin propiedad (búsquedas generales). Asóciales una propiedad o elimínalas antes de bajar de y8z9a0b1c2d3.';
            END IF;
        END
        $$
        """
    )
    op.alter_column('property_alerts', 'property_id', existing_type=sa.Integer(), nullable=False)

    op.drop_column('property_alerts', 'property_linked_at')
    op.drop_column('property_alerts', 'origin')

    op.drop_index('ix_property_alerts_company_id', table_name='property_alerts')
    op.drop_constraint('fk_property_alerts_company_id', 'property_alerts', type_='foreignkey')
    op.drop_column('property_alerts', 'company_id')
