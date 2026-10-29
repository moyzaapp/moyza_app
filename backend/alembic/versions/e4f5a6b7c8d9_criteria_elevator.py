"""filtro de ascensor en el perfil de búsqueda del comprador

PLAN_PERFIL_ZONAS.md, fase C: columna `elevator` en `buyer_search_criteria`
(Boolean, nullable). NULL = indiferente (lo que queda en los perfiles que ya
existen), true = con ascensor, false = sin ascensor. El cruce con las
propiedades usa su `num_ascensores` (sin cambios en `properties`).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('buyer_search_criteria', sa.Column('elevator', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('buyer_search_criteria', 'elevator')
