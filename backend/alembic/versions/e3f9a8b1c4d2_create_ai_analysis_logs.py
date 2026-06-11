"""create ai_analysis_logs table

Revision ID: e3f9a8b1c4d2
Revises: c2c34d595013
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f9a8b1c4d2'
down_revision: Union[str, Sequence[str], None] = 'c2c34d595013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ai_analysis_logs table for AI audit trail."""
    op.create_table(
        'ai_analysis_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=True),
        sa.Column('analysis_type', sa.String(length=50), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('temperature', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('estimated_cost', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('response_time_seconds', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('used_in_report', sa.Boolean(), nullable=False),
        sa.Column('extra_metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Crear índices para mejorar performance de queries
    op.create_index(
        op.f('ix_ai_analysis_logs_id'),
        'ai_analysis_logs',
        ['id'],
        unique=False
    )
    op.create_index(
        op.f('ix_ai_analysis_logs_property_id'),
        'ai_analysis_logs',
        ['property_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_ai_analysis_logs_report_id'),
        'ai_analysis_logs',
        ['report_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_ai_analysis_logs_analysis_type'),
        'ai_analysis_logs',
        ['analysis_type'],
        unique=False
    )
    op.create_index(
        op.f('ix_ai_analysis_logs_created_at'),
        'ai_analysis_logs',
        ['created_at'],
        unique=False
    )


def downgrade() -> None:
    """Drop ai_analysis_logs table."""
    op.drop_index(op.f('ix_ai_analysis_logs_created_at'), table_name='ai_analysis_logs')
    op.drop_index(op.f('ix_ai_analysis_logs_analysis_type'), table_name='ai_analysis_logs')
    op.drop_index(op.f('ix_ai_analysis_logs_report_id'), table_name='ai_analysis_logs')
    op.drop_index(op.f('ix_ai_analysis_logs_property_id'), table_name='ai_analysis_logs')
    op.drop_index(op.f('ix_ai_analysis_logs_id'), table_name='ai_analysis_logs')
    op.drop_table('ai_analysis_logs')
