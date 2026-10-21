"""positions

Штатка из должностей: у строки штатки появляется название должности.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22 10:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('staffing_lines', sa.Column('position', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('staffing_lines', 'position')
