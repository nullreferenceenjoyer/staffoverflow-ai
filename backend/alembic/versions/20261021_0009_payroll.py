"""payroll

Средний оклад за ставку в строке штатки и версии штатного расписания: по ним
считается ФОТ и видно, как он менялся при изменении штатки.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21 10:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('staffing_lines', sa.Column('salary_rub', sa.Numeric(10, 2), nullable=True))
    op.create_table(
        'staffing_schedule_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.String(length=9), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('approved_fte', sa.Numeric(8, 2), nullable=False),
        sa.Column('occupied_fte', sa.Numeric(8, 2), nullable=True),
        sa.Column('payroll_approved', sa.Numeric(14, 2), nullable=True),
        sa.Column('payroll_occupied', sa.Numeric(14, 2), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['schedule_id'], ['staffing_schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_staffing_schedule_versions_schedule_id'), 'staffing_schedule_versions', ['schedule_id'], unique=False)
    op.create_index('ix_schedule_versions_org_year', 'staffing_schedule_versions', ['organization_id', 'academic_year'], unique=False)


def downgrade() -> None:
    op.drop_table('staffing_schedule_versions')
    op.drop_column('staffing_lines', 'salary_rub')
