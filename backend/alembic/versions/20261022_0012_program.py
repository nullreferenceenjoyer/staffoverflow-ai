"""program

Программа оптимизации штатных расписаний: результаты по школам, расчёт по должностям,
уволенные сотрудники. Простые входные данные для расчёта уборщиц и хозотдела.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22 12:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('institution_metrics', sa.Column('cleaners_fte', sa.Numeric(7, 2), nullable=True))
    op.add_column('institution_metrics', sa.Column('maintenance_fte', sa.Numeric(7, 2), nullable=True))
    op.create_table(
        'program_schools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('total', sa.Numeric(9, 3), nullable=False),
        sa.Column('vacancies', sa.Numeric(9, 3), nullable=False),
        sa.Column('load_reduction', sa.Numeric(9, 3), nullable=False),
        sa.Column('resignations', sa.Numeric(9, 3), nullable=False),
        sa.Column('layoffs', sa.Numeric(9, 3), nullable=False),
        sa.Column('hours', sa.Integer(), nullable=False),
        sa.Column('staff_units', sa.Integer(), nullable=False),
        sa.Column('orders_note', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
    )
    op.create_table(
        'program_positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('before_fte', sa.Numeric(10, 3), nullable=False),
        sa.Column('cut_fte', sa.Numeric(10, 3), nullable=False),
        sa.Column('after_fte', sa.Numeric(10, 3), nullable=False),
        sa.Column('local_cut', sa.Numeric(10, 3), nullable=True),
        sa.Column('local_economy_month', sa.Numeric(14, 2), nullable=True),
        sa.Column('regional_cut', sa.Numeric(10, 3), nullable=True),
        sa.Column('regional_economy_month', sa.Numeric(14, 2), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'dismissals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('position', sa.String(length=300), nullable=False),
        sa.Column('fte', sa.Numeric(6, 2), nullable=False),
        sa.Column('basis', sa.String(length=16), nullable=False),
        sa.Column('article', sa.String(length=200), nullable=True),
        sa.Column('order_number', sa.String(length=60), nullable=True),
        sa.Column('order_date', sa.Date(), nullable=True),
        sa.Column('dismissed_on', sa.Date(), nullable=True),
        sa.Column('notified_on', sa.Date(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dismissals_organization_id'), 'dismissals', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_table('dismissals')
    op.drop_table('program_positions')
    op.drop_table('program_schools')
    op.drop_column('institution_metrics', 'maintenance_fte')
    op.drop_column('institution_metrics', 'cleaners_fte')
