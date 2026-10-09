"""add agents to property visits

Añade a `property_visits` el agente que realizó la visita (`agent_id`) y un
acompañante opcional (`companion_agent_id`). Hasta ahora la visita se
atribuía al captador de la propiedad.

Backfill de `agent_id` (SQL puro, sin importar modelos):
  1. El agente cuyo email coincide con el del usuario que creó la visita.
  2. Si no hay coincidencia, el agente captador de la propiedad.
  3. Lo que quede en NULL se deja NULL (la ficha sigue cayendo en el
     agente de la propiedad).

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-10-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's2t3u4v5w6x7'
down_revision = 'r1s2t3u4v5w6'
branch_labels = None
depends_on = None


AGENT_COLUMNS = ['agent_id', 'companion_agent_id']


def upgrade():
    for column in AGENT_COLUMNS:
        op.add_column(
            'property_visits',
            sa.Column(
                column,
                sa.Integer(),
                sa.ForeignKey(
                    'agents.id',
                    name=f'fk_property_visits_{column}',
                    ondelete='SET NULL'
                ),
                nullable=True
            )
        )
        op.create_index(f'ix_property_visits_{column}', 'property_visits', [column])

    # 1. Agente del usuario que creó la visita (vínculo por email, igual
    #    que get_agent_from_user)
    op.execute("""
        UPDATE property_visits pv
        SET agent_id = a.id
        FROM users u
        JOIN agents a ON a.email = u.email
        WHERE pv.created_by = u.id
          AND pv.agent_id IS NULL
    """)

    # 2. Si no, el agente captador de la propiedad
    op.execute("""
        UPDATE property_visits pv
        SET agent_id = p.agent_id
        FROM properties p
        WHERE pv.property_id = p.id
          AND pv.agent_id IS NULL
          AND p.agent_id IS NOT NULL
    """)


def downgrade():
    for column in reversed(AGENT_COLUMNS):
        op.drop_index(f'ix_property_visits_{column}', table_name='property_visits')
        op.drop_constraint(f'fk_property_visits_{column}', 'property_visits', type_='foreignkey')
        op.drop_column('property_visits', column)
