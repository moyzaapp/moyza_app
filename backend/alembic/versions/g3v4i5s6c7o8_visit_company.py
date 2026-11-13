"""empresa propia de la visita (property_visits.company_id)

PLAN_VISITAS_OTRA_EMPRESA.md (fase A): un agente puede registrar visitas a
propiedades de cualquier empresa. La visita deja de heredar la empresa de la
propiedad y guarda la suya: la empresa desde la que se registra (la del
agente). De ella dependen el alcance de las visitas (`scope_visits`), la
marca de la ficha y la métrica "Hojas de visita".

- `property_visits.company_id`: nullable para el backfill (= empresa de la
  propiedad de cada visita, así nada cambia para las existentes), luego
  NOT NULL, con índice (alcance por empresa).

Downgrade: si hay visitas registradas en una empresa distinta de la de su
propiedad (visitas cruzadas), se detiene con un mensaje claro en vez de
perder esa información (pasarían a contar en la empresa de la propiedad).

Revision ID: g3v4i5s6c7o8
Revises: f2u3v4i5e6w7
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'g3v4i5s6c7o8'
down_revision = 'f2u3v4i5e6w7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('property_visits', sa.Column(
        'company_id', sa.Integer(),
        sa.ForeignKey('companies.id', name='fk_property_visits_company_id'),
        nullable=True,
    ))
    op.execute(
        "UPDATE property_visits SET company_id = "
        "(SELECT company_id FROM properties WHERE properties.id = property_visits.property_id)"
    )
    op.alter_column('property_visits', 'company_id', existing_type=sa.Integer(), nullable=False)
    op.create_index('ix_property_visits_company_id', 'property_visits', ['company_id'])


def downgrade() -> None:
    # No se pierde la empresa de las visitas cruzadas: el downgrade se detiene
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM property_visits v
                JOIN properties p ON p.id = v.property_id
                WHERE v.company_id <> p.company_id
            ) THEN
                RAISE EXCEPTION 'Hay visitas registradas en una empresa distinta de la de su propiedad. Revísalas antes de bajar de g3v4i5s6c7o8.';
            END IF;
        END
        $$
        """
    )
    op.drop_index('ix_property_visits_company_id', table_name='property_visits')
    op.drop_constraint('fk_property_visits_company_id', 'property_visits', type_='foreignkey')
    op.drop_column('property_visits', 'company_id')
