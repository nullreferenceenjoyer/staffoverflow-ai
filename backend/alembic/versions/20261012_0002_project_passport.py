"""project passport

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 18:17
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('digital_tools',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('function_code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('coverage_pct', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('function_code')
    )
    op.create_table('programs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('municipality_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=400), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('target_fot_cut_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('baseline', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('baseline_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('municipality_id')
    )
    op.create_table('milestones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('program_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=400), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('responsible', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('notifications', sa.Column('sent_to_max', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('project_items', sa.Column('vacant_rate', sa.Numeric(precision=8, scale=2), server_default='0', nullable=False))
    op.add_column('users', sa.Column('max_chat_id', sa.BigInteger(), nullable=True))
    op.create_unique_constraint('users_max_chat_id_key', 'users', ['max_chat_id'])


def downgrade() -> None:
    # https://alembic.sqlalchemy.org/en/latest/naming.html
    op.drop_constraint('users_max_chat_id_key', 'users', type_='unique')
    op.drop_column('users', 'max_chat_id')
    op.drop_column('project_items', 'vacant_rate')
    op.drop_column('notifications', 'sent_to_max')
    op.drop_table('milestones')
    op.drop_table('programs')
    op.drop_table('digital_tools')
