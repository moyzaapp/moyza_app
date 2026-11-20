"""varios tipos de inmueble en el perfil de búsqueda del comprador

Columna `property_types` en `buyer_search_criteria` (JSON, nullable): lista de
tipos marcados (["Piso", "Casa"]); NULL = cualquier tipo. Los perfiles que ya
tenían `property_type` pasan a una lista con ese único tipo. `property_type`
se conserva con el texto de la lista ("Piso, Casa").

Revision ID: o1v2a3b4c5d6
Revises: n0u1z2a3b4c5
Create Date: 2026-11-19
"""
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'o1v2a3b4c5d6'
down_revision = 'n0u1z2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('buyer_search_criteria', sa.Column('property_types', sa.JSON(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, property_type FROM buyer_search_criteria "
        "WHERE property_type IS NOT NULL AND trim(property_type) <> ''"
    )).fetchall()
    for row_id, property_type in rows:
        bind.execute(
            sa.text("UPDATE buyer_search_criteria SET property_types = CAST(:types AS JSON) WHERE id = :id"),
            {"types": json.dumps([property_type.strip()], ensure_ascii=False), "id": row_id},
        )


def downgrade() -> None:
    op.drop_column('buyer_search_criteria', 'property_types')
