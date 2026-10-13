"""sites and requests

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 11:42
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('buildings', sa.Column('address', sa.String(length=300), nullable=True))
    op.add_column('buildings', sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True))
    op.add_column('buildings', sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True))
    op.add_column('buildings', sa.Column('capacity', sa.Integer(), nullable=True))
    op.add_column('buildings', sa.Column('occupancy', sa.Integer(), nullable=True))
    op.add_column('buildings', sa.Column('rgis_id', sa.String(length=64), nullable=True))
    op.create_unique_constraint('buildings_rgis_id_key', 'buildings', ['rgis_id'])

    op.add_column('staff_positions', sa.Column('building_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_staff_positions_building_id'), 'staff_positions', ['building_id'], unique=False)
    op.create_foreign_key('staff_positions_building_id_fkey', 'staff_positions', 'buildings', ['building_id'], ['id'], ondelete='SET NULL')

    op.add_column('incoming_requests', sa.Column('building_id', sa.Integer(), nullable=True))
    op.add_column('incoming_requests', sa.Column('location', sa.String(length=200), nullable=True))
    op.add_column('incoming_requests', sa.Column('title', sa.String(length=200), nullable=True))
    op.add_column('incoming_requests', sa.Column('kind', sa.String(length=32), server_default='planned', nullable=False))
    op.add_column('incoming_requests', sa.Column('assignee_id', sa.Integer(), nullable=True))
    op.add_column('incoming_requests', sa.Column('due_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incoming_requests', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incoming_requests', sa.Column('hold_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incoming_requests', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incoming_requests', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incoming_requests', sa.Column('last_reminder_on', sa.Date(), nullable=True))
    # У старых обращений заголовка не было — берём начало текста
    op.execute("UPDATE incoming_requests SET title = left(text, 120)")
    op.alter_column('incoming_requests', 'title', nullable=False)
    op.alter_column('incoming_requests', 'status', existing_type=sa.String(length=16), type_=sa.String(length=32))
    op.create_index(op.f('ix_incoming_requests_assignee_id'), 'incoming_requests', ['assignee_id'], unique=False)
    op.create_index('ix_requests_status_due', 'incoming_requests', ['status', 'due_at'], unique=False)
    op.create_foreign_key('incoming_requests_building_id_fkey', 'incoming_requests', 'buildings', ['building_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('incoming_requests_assignee_id_fkey', 'incoming_requests', 'users', ['assignee_id'], ['id'], ondelete='SET NULL')

    op.create_table('request_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['incoming_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_events_request_id'), 'request_events', ['request_id'], unique=False)

    op.add_column('notifications', sa.Column('request_id', sa.Integer(), nullable=True))
    op.create_foreign_key('notifications_request_id_fkey', 'notifications', 'incoming_requests', ['request_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('notifications_request_id_fkey', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'request_id')
    op.drop_index(op.f('ix_request_events_request_id'), table_name='request_events')
    op.drop_table('request_events')

    op.drop_constraint('incoming_requests_assignee_id_fkey', 'incoming_requests', type_='foreignkey')
    op.drop_constraint('incoming_requests_building_id_fkey', 'incoming_requests', type_='foreignkey')
    op.drop_index('ix_requests_status_due', table_name='incoming_requests')
    op.drop_index(op.f('ix_incoming_requests_assignee_id'), table_name='incoming_requests')
    for column in ('last_reminder_on', 'closed_at', 'resolved_at', 'hold_since', 'started_at',
                   'due_at', 'assignee_id', 'kind', 'title', 'location', 'building_id'):
        op.drop_column('incoming_requests', column)

    op.drop_constraint('staff_positions_building_id_fkey', 'staff_positions', type_='foreignkey')
    op.drop_index(op.f('ix_staff_positions_building_id'), table_name='staff_positions')
    op.drop_column('staff_positions', 'building_id')

    op.drop_constraint('buildings_rgis_id_key', 'buildings', type_='unique')
    for column in ('rgis_id', 'occupancy', 'capacity', 'longitude', 'latitude', 'address'):
        op.drop_column('buildings', column)
