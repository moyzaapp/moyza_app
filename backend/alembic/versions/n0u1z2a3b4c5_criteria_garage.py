"""filtro de garaje en el perfil de búsqueda del comprador

Columna `garage` en `buyer_search_criteria` (Boolean, nullable). NULL =
indiferente (lo que queda en los perfiles que ya existen), true = con garaje.
El cruce con las propiedades usa su `num_garaje_aparcam` (>= 1; sin cambios
en `properties`).

Revision ID: n0u1z2a3b4c5
Revises: m9t0y1z2a3b4
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'n0u1z2a3b4c5'
down_revision = 'm9t0y1z2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('buyer_search_criteria', sa.Column('garage', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('buyer_search_criteria', 'garage')
