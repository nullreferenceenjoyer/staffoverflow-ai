"""workload

Число кабинетов в показателях учреждения (норматив «1 уборщик на 30 кабинетов») и
таблица настроек: нормы загрузки хозслужбы и бригад правят в интерфейсе.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21 18:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('institution_metrics', sa.Column('rooms_count', sa.Integer(), nullable=True))
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_column('institution_metrics', 'rooms_count')
