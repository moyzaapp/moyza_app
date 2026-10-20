"""buyer_search_criteria: country y province

PLAN_PERFIL_UBICACION.md: la ubicación del perfil de búsqueda pasa a ser una
cascada País → Provincia → Población → Zona. El perfil guarda el país y la
provincia elegidos para que "Todas las poblaciones" signifique cualquier
población de esa provincia (también las que entren después). Las propiedades
NO cambian: su provincia se deduce del código postal (app/core/geo.py).

Columnas nuevas, nullable y sin backfill: los perfiles existentes siguen
filtrando por sus poblaciones y zonas como hasta ahora. Downgrade: las quita.

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
Create Date: 2026-10-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a0b1c2d3e4f5'
down_revision = 'z9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('buyer_search_criteria', sa.Column('country', sa.String(), nullable=True))
    op.add_column('buyer_search_criteria', sa.Column('province', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('buyer_search_criteria', 'province')
    op.drop_column('buyer_search_criteria', 'country')
