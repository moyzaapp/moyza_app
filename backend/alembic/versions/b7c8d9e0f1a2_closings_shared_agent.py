"""cierres compartidos por dos agentes

PLAN_CIERRES_DOS_AGENTES.md, fase A: un cierre compartido son dos registros
de `closings` (uno por agente) enlazados por `pair_key`, cada uno con
`shared_with_agent_id` apuntando al otro agente. Los cierres existentes
quedan como de un solo agente (decisión 4: no se enlazan a posteriori).

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('closings', sa.Column(
        'shared_with_agent_id', sa.Integer(),
        sa.ForeignKey('agents.id', name='fk_closings_shared_with_agent_id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('closings', sa.Column('pair_key', sa.String(length=36), nullable=True))
    op.create_index('ix_closings_pair_key', 'closings', ['pair_key'])


def downgrade() -> None:
    op.drop_index('ix_closings_pair_key', table_name='closings')
    op.drop_column('closings', 'pair_key')
    op.drop_column('closings', 'shared_with_agent_id')
