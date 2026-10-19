"""brigades and effort

Выездные бригады с закреплёнными учреждениями, координаты учреждений,
оценка трудоёмкости заявок и этапы крупных заявок.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 10:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True))
    op.add_column('organizations', sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True))

    op.create_table(
        'brigades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('municipality_id', sa.Integer(), nullable=True),
        sa.Column('base_address', sa.String(length=300), nullable=True),
        sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column('topics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'brigade_organizations',
        sa.Column('brigade_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['brigade_id'], ['brigades.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('brigade_id', 'organization_id'),
    )

    op.add_column('users', sa.Column('brigade_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_brigade_id'), 'users', ['brigade_id'], unique=False)
    op.create_foreign_key('users_brigade_id_fkey', 'users', 'brigades', ['brigade_id'], ['id'], ondelete='SET NULL')

    op.add_column('incoming_requests', sa.Column('brigade_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_incoming_requests_brigade_id'), 'incoming_requests', ['brigade_id'], unique=False)
    op.create_foreign_key('incoming_requests_brigade_id_fkey', 'incoming_requests', 'brigades', ['brigade_id'], ['id'], ondelete='SET NULL')
    op.add_column('incoming_requests', sa.Column('effort_hours', sa.Numeric(precision=6, scale=1), nullable=True))
    op.add_column('incoming_requests', sa.Column('complexity', sa.String(length=32), server_default='simple', nullable=False))
    op.add_column('incoming_requests', sa.Column('effort_by', sa.String(length=8), nullable=True))
    op.add_column('incoming_requests', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_incoming_requests_parent_id'), 'incoming_requests', ['parent_id'], unique=False)
    op.create_foreign_key('incoming_requests_parent_id_fkey', 'incoming_requests', 'incoming_requests', ['parent_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('incoming_requests_parent_id_fkey', 'incoming_requests', type_='foreignkey')
    op.drop_index(op.f('ix_incoming_requests_parent_id'), table_name='incoming_requests')
    for column in ('parent_id', 'effort_by', 'complexity', 'effort_hours'):
        op.drop_column('incoming_requests', column)
    op.drop_constraint('incoming_requests_brigade_id_fkey', 'incoming_requests', type_='foreignkey')
    op.drop_index(op.f('ix_incoming_requests_brigade_id'), table_name='incoming_requests')
    op.drop_column('incoming_requests', 'brigade_id')
    op.drop_constraint('users_brigade_id_fkey', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_brigade_id'), table_name='users')
    op.drop_column('users', 'brigade_id')
    op.drop_table('brigade_organizations')
    op.drop_table('brigades')
    op.drop_column('organizations', 'longitude')
    op.drop_column('organizations', 'latitude')
