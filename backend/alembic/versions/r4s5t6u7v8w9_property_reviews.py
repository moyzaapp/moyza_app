"""revisión de las propiedades nuevas por el captador

PLAN_REVISION_PROPIEDADES_NUEVAS.md §4.1: tabla `property_reviews`, una fila
por propiedad. La ETL del CRM escribe en `properties` desde fuera de la app y
la tabla no tiene `created_at`, así que «propiedad nueva» = propiedad sin fila
aquí (P1).

Backfill: todas las propiedades que ya existen al desplegar quedan `skipped`,
así nada anterior pide revisión. A partir de aquí el job
`register_property_reviews` crea las filas de las que vayan entrando.

Downgrade: borra la tabla (se pierden las revisiones hechas).

Revision ID: r4s5t6u7v8w9
Revises: q3x4y5z6a7b8
Create Date: 2026-11-24 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'r4s5t6u7v8w9'
down_revision = 'q3x4y5z6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'property_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(),
                  sa.ForeignKey('properties.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.Integer(),
                  sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('agent_comment', sa.Text(), nullable=True),
        sa.Column('admin_comment', sa.Text(), nullable=True),
        sa.Column('rounds', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('reminded_at', sa.DateTime(), nullable=True),
        sa.Column('flagged_at', sa.DateTime(), nullable=True),
        sa.Column('fixed_at', sa.DateTime(), nullable=True),
        sa.Column('fixed_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ok_at', sa.DateTime(), nullable=True),
        sa.Column('ok_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('property_id', name='uq_property_reviews_property_id'),
    )
    op.create_index('ix_property_reviews_id', 'property_reviews', ['id'])
    op.create_index('ix_property_reviews_status_agent', 'property_reviews', ['status', 'agent_id'])

    # Lo que ya existe no pide revisión (P1). Hora UTC naive, como el resto de fechas.
    op.execute(
        "INSERT INTO property_reviews (property_id, agent_id, status, rounds, created_at) "
        "SELECT id, agent_id, 'skipped', 0, (now() AT TIME ZONE 'UTC') FROM properties"
    )


def downgrade() -> None:
    op.drop_index('ix_property_reviews_status_agent', table_name='property_reviews')
    op.drop_index('ix_property_reviews_id', table_name='property_reviews')
    op.drop_table('property_reviews')
