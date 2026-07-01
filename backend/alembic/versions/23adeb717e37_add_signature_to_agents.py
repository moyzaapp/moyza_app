"""add_signature_to_agents

Revision ID: 23adeb717e37
Revises: 2127fcfd5306
Create Date: 2026-06-29 18:13:54.633500

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '23adeb717e37'
down_revision: Union[str, Sequence[str], None] = '2127fcfd5306'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agents', sa.Column('signature_filename', sa.String(), nullable=True))
    op.add_column('agents', sa.Column('signature_filepath', sa.String(), nullable=True))
    op.add_column('agents', sa.Column('signature_uploaded_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'signature_uploaded_at')
    op.drop_column('agents', 'signature_filepath')
    op.drop_column('agents', 'signature_filename')
