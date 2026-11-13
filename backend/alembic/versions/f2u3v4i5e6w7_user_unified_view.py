"""vista unificada para agentes: opción por usuario y empresa principal

PLAN_VISTA_UNIFICADA_AGENTES.md §2.1 (fase A):

- `users.company_switch_enabled`: el usuario conserva el selector de empresa
  (vista por empresa). Por defecto False: un agente trabaja con todas sus
  empresas a la vez, sin selector. El admin siempre tiene selector.
- `users.primary_company_id`: empresa principal del usuario (marca del
  sidebar en la vista unificada y empresa por defecto de lo que crea). NULL =
  la primera de sus empresas permitidas (MOYZA por defecto). SET NULL si se
  borrara la empresa. Se rellena para los usuarios existentes con la primera
  empresa marcada en su usuario (menor id de `user_companies`), lo mismo que
  guarda Editar usuario si no se elige: así un usuario solo de MOES conserva
  la marca MOES aunque su ficha de agente esté también en MOYZA.

Revision ID: f2u3v4i5e6w7
Revises: e1n2v3p4r5o6
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f2u3v4i5e6w7'
down_revision = 'e1n2v3p4r5o6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column(
        'company_switch_enabled', sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column('users', sa.Column(
        'primary_company_id', sa.Integer(),
        sa.ForeignKey('companies.id', name='fk_users_primary_company_id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.execute(
        "UPDATE users SET primary_company_id = ("
        " SELECT MIN(uc.company_id) FROM user_companies uc WHERE uc.user_id = users.id"
        ") WHERE primary_company_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_primary_company_id', 'users', type_='foreignkey')
    op.drop_column('users', 'primary_company_id')
    op.drop_column('users', 'company_switch_enabled')
