"""add_dni_to_agents

Revision ID: f432dcf50003
Revises: 23adeb717e37
Create Date: 2026-06-29 18:35:52.050901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f432dcf50003'
down_revision: Union[str, Sequence[str], None] = '23adeb717e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agents', sa.Column('dni', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'dni')
