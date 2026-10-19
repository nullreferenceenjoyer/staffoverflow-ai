"""requests and staffing only

Убираются проекты штатных, задачи, паспорт проекта, база знаний и боты.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 20:40
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('notifications', 'task_id')
    op.drop_column('notifications', 'sent_to_telegram')
    op.drop_column('notifications', 'sent_to_max')
    op.drop_column('users', 'telegram_chat_id')
    op.drop_column('users', 'max_chat_id')
    op.drop_column('norms', 'document_id')
    op.drop_column('norms', 'centralization_effect')

    for table in ('tasks', 'workflow_templates', 'generated_documents', 'project_items',
                  'projects', 'milestones', 'programs', 'digital_tools', 'knowledge_chunks',
                  'knowledge_documents'):
        op.drop_table(table)


def downgrade() -> None:
    # Данные удалённых разделов не восстановить, а пустые таблицы без кода не нужны
    raise NotImplementedError("Откат на 0003 не поддерживается — восстановите базу из резервной копии")
