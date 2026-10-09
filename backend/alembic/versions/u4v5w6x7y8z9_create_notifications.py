"""create notifications (in-app)

PLAN_DASHBOARD_INICIO.md §4.1: tabla de notificaciones in-app por usuario y
empresa. Índice compuesto (user_id, read_at, created_at) para el contador de
no leídas y el listado. Las leídas con más de 90 días las borra el scheduler.

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-10-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u4v5w6x7y8z9'
down_revision = 't3u4v5w6x7y8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('read_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_notifications_id', 'notifications', ['id'])
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_company_id', 'notifications', ['company_id'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('ix_notifications_user_read_created', 'notifications', ['user_id', 'read_at', 'created_at'])


def downgrade():
    op.drop_index('ix_notifications_user_read_created', table_name='notifications')
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_company_id', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_index('ix_notifications_id', table_name='notifications')
    op.drop_table('notifications')
