"""merge visit fields migrations

Revision ID: 2127fcfd5306
Revises: a9b8c7d6e5f4, g5h6i7j8k9l0
Create Date: 2026-06-15 11:16:12.583912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2127fcfd5306'
down_revision: Union[str, Sequence[str], None] = ('a9b8c7d6e5f4', 'g5h6i7j8k9l0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
