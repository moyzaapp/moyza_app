"""add visit sheet fields

Revision ID: a9b8c7d6e5f4
Revises: f4a2b3c5d6e7
Create Date: 2026-06-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b8c7d6e5f4'
down_revision = 'f4a2b3c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'property_visits',
        sa.Column('visit_sheet_filename', sa.String(), nullable=True)
    )
    op.add_column(
        'property_visits',
        sa.Column('visit_sheet_filepath', sa.String(), nullable=True)
    )
    op.add_column(
        'property_visits',
        sa.Column('visit_sheet_generated_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'property_visits',
        sa.Column('visit_sheet_sent_to', sa.String(), nullable=True)
    )


def downgrade():
    op.drop_column('property_visits', 'visit_sheet_sent_to')
    op.drop_column('property_visits', 'visit_sheet_generated_at')
    op.drop_column('property_visits', 'visit_sheet_filepath')
    op.drop_column('property_visits', 'visit_sheet_filename')
