"""baja lógica de usuarios y agentes

PLAN_BAJA_USUARIOS.md, fase A (§3): fecha de baja en `users` (`is_active` ya
existe; NULL cuenta como activo) y estado propio en `agents`: `is_active`
(NOT NULL, true por defecto para las fichas que ya existen, indexado) y
`deactivated_at`. Un inactivo no entra en la app ni aparece en los
selectores de asignación; su historial se conserva.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime(), nullable=True))
    # agents
    op.add_column('agents', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('agents', sa.Column('deactivated_at', sa.DateTime(), nullable=True))
    op.create_index('ix_agents_is_active', 'agents', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_agents_is_active', table_name='agents')
    op.drop_column('agents', 'deactivated_at')
    op.drop_column('agents', 'is_active')
    op.drop_column('users', 'deactivated_at')
