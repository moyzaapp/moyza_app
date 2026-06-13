"""update report log fk set null

Revision ID: c2c34d595013
Revises: 5573324973ba
Create Date: 2026-06-10 23:23:59.941369

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c2c34d595013'
down_revision: Union[str, Sequence[str], None] = '5573324973ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create report_job_logs table if it doesn't exist
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'report_job_logs' not in inspector.get_table_names():
        # Create the table
        op.create_table(
            'report_job_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('property_id', sa.Integer(), nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=True),
            sa.Column('job_run_at', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('stage', sa.String(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('retry_count', sa.Integer(), nullable=False),
            sa.Column('duration_seconds', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('metadatas', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_report_job_logs_id'), 'report_job_logs', ['id'], unique=False)
        op.create_index(op.f('ix_report_job_logs_property_id'), 'report_job_logs', ['property_id'], unique=False)
        op.create_index(op.f('ix_report_job_logs_job_run_at'), 'report_job_logs', ['job_run_at'], unique=False)
        op.create_foreign_key(None, 'report_job_logs', 'properties', ['property_id'], ['id'])
        op.create_foreign_key(None, 'report_job_logs', 'reports', ['report_id'], ['id'], ondelete='SET NULL')
    else:
        # Table exists, just update the foreign key
        op.drop_constraint(op.f('report_job_logs_report_id_fkey'), 'report_job_logs', type_='foreignkey')
        op.create_foreign_key(None, 'report_job_logs', 'reports', ['report_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    # Check if table exists
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'report_job_logs' in inspector.get_table_names():
        op.drop_index(op.f('ix_report_job_logs_job_run_at'), table_name='report_job_logs')
        op.drop_index(op.f('ix_report_job_logs_property_id'), table_name='report_job_logs')
        op.drop_index(op.f('ix_report_job_logs_id'), table_name='report_job_logs')
        op.drop_table('report_job_logs')
