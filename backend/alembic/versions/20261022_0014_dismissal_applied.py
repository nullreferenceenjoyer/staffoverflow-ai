"""dismissal applied

Увольнение учитывается в штатке школы: у записи — строка штатки и на сколько уменьшили
«занято» (и совмещение, если оно стало больше занятого). По ним изменение и откатывается.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-22 18:00
"""
import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dismissals', sa.Column('line_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_dismissals_line', 'dismissals', 'staffing_lines', ['line_id'],
                          ['id'], ondelete='SET NULL')
    op.add_column('dismissals', sa.Column('applied_fte', sa.Numeric(6, 2), nullable=True))
    op.add_column('dismissals', sa.Column('applied_combined', sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('dismissals', 'applied_combined')
    op.drop_column('dismissals', 'applied_fte')
    op.drop_constraint('fk_dismissals_line', 'dismissals', type_='foreignkey')
    op.drop_column('dismissals', 'line_id')
