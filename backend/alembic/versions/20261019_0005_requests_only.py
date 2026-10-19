"""requests only

Убирается анализ штатного расписания: ставки, контингент, нормативы и сведения
о зданиях, которые нужны были только для расчётов. У корпуса остаются название и адрес.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19 22:10
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ставки ссылаются на корпуса, поэтому удаляются первыми
    for table in ('staff_positions', 'enrollments', 'norms'):
        op.drop_table(table)
    for column in ('area_sqm', 'floors', 'year_built', 'condition', 'latitude', 'longitude',
                   'capacity', 'occupancy', 'rgis_id'):
        op.drop_column('buildings', column)


def downgrade() -> None:
    # Данные удалённых разделов не восстановить, а пустые таблицы без кода не нужны
    raise NotImplementedError("Откат на 0004 не поддерживается — восстановите базу из резервной копии")
