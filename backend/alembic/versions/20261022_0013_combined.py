"""combined

Совмещение в строке штатки: часть занятых ставок, которую снимают уменьшением нагрузки.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-22 15:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('staffing_lines', sa.Column('combined_fte', sa.Numeric(7, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('staffing_lines', 'combined_fte')
