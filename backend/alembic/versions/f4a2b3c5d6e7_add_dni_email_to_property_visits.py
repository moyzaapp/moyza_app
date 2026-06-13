"""add dni email to property visits

Revision ID: f4a2b3c5d6e7
Revises: e3f9a8b1c4d2
Create Date: 2026-06-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4a2b3c5d6e7'
down_revision = 'e3f9a8b1c4d2'
branch_labels = None
depends_on = None


def upgrade():
    # Add dni and email columns to property_visits table
    op.add_column('property_visits', sa.Column('dni', sa.String(), nullable=True))
    op.add_column('property_visits', sa.Column('email', sa.String(), nullable=True))


def downgrade():
    # Remove dni and email columns from property_visits table
    op.drop_column('property_visits', 'email')
    op.drop_column('property_visits', 'dni')
