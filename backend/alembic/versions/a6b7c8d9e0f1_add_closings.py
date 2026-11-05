"""cierres registrados a mano

PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md, fase A (§2.1): tabla `closings` con
un registro por cierre y por agente (fecha, Venta / Alquiler, propiedad
opcional y nota). La métrica "Cierres" pasa a contar estos registros en
lugar de los seguimientos «Cerrado» de las alertas.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a6b7c8d9e0f1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'closings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('agents.id'), nullable=False),
        sa.Column('business_type', sa.String(), nullable=False),
        sa.Column('closed_on', sa.Date(), nullable=False),
        sa.Column('property_id', sa.Integer(),
                  sa.ForeignKey('properties.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_closings_id', 'closings', ['id'])
    op.create_index('ix_closings_company_agent_closed_on', 'closings',
                    ['company_id', 'agent_id', 'closed_on'])


def downgrade() -> None:
    op.drop_index('ix_closings_company_agent_closed_on', table_name='closings')
    op.drop_index('ix_closings_id', table_name='closings')
    op.drop_table('closings')
