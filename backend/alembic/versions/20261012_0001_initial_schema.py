"""initial schema

Revision ID: 0001
Revises: -
Create Date: 2026-10-12 16:36
"""
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('user_email', sa.String(length=200), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity', sa.String(length=60), nullable=True),
    sa.Column('entity_id', sa.String(length=60), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_created_at'), 'audit_log', ['created_at'], unique=False)
    op.create_table('knowledge_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=400), nullable=False),
    sa.Column('doc_type', sa.String(length=40), nullable=False),
    sa.Column('source_ref', sa.String(length=400), nullable=True),
    sa.Column('file_path', sa.String(length=400), nullable=True),
    sa.Column('is_summary', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('municipalities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('workflow_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_chunks_document_id'), 'knowledge_chunks', ['document_id'], unique=False)
    op.create_table('norms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('function_code', sa.String(length=40), nullable=False),
    sa.Column('org_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('driver', sa.String(length=40), nullable=False),
    sa.Column('unit_size', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('per_unit', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('base', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('threshold', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('min_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('max_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('rounding', sa.Numeric(precision=4, scale=2), nullable=False),
    sa.Column('centralization_effect', sa.Numeric(precision=4, scale=2), nullable=False),
    sa.Column('source_kind', sa.String(length=16), nullable=False),
    sa.Column('legal_ref', sa.String(length=500), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('organizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('municipality_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('org_type', sa.String(length=32), nullable=False),
    sa.Column('address', sa.String(length=300), nullable=True),
    sa.Column('external_id', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_id')
    )
    op.create_index(op.f('ix_organizations_municipality_id'), 'organizations', ['municipality_id'], unique=False)
    op.create_table('buildings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('area_sqm', sa.Numeric(precision=10, scale=1), nullable=False),
    sa.Column('floors', sa.Integer(), nullable=False),
    sa.Column('year_built', sa.Integer(), nullable=True),
    sa.Column('condition', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_buildings_organization_id'), 'buildings', ['organization_id'], unique=False)
    op.create_table('enrollments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('academic_year', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=32), nullable=False),
    sa.Column('study_form', sa.String(length=32), nullable=False),
    sa.Column('classes_count', sa.Integer(), nullable=False),
    sa.Column('students_count', sa.Integer(), nullable=False),
    sa.Column('special_needs_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'academic_year', 'level', 'study_form')
    )
    op.create_index(op.f('ix_enrollments_organization_id'), 'enrollments', ['organization_id'], unique=False)
    op.create_table('staff_positions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('department', sa.String(length=200), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('function_code', sa.String(length=40), nullable=False),
    sa.Column('rate', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('monthly_pay', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('employee_ref', sa.String(length=32), nullable=True),
    sa.Column('weekly_hours', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('duties', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_staff_org_function', 'staff_positions', ['organization_id', 'function_code'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('municipality_id', sa.Integer(), nullable=True),
    sa.Column('organization_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('telegram_chat_id')
    )
    op.create_table('incoming_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('topic', sa.String(length=40), nullable=False),
    sa.Column('routed_role', sa.String(length=32), nullable=False),
    sa.Column('classified_by', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incoming_requests_organization_id'), 'incoming_requests', ['organization_id'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('municipality_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('rate_delta', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('fot_effect_year', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_municipality_id'), 'projects', ['municipality_id'], unique=False)
    op.create_table('generated_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('file_path', sa.String(length=400), nullable=False),
    sa.Column('written_by_llm', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_documents_project_id'), 'generated_documents', ['project_id'], unique=False)
    op.create_table('project_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=True),
    sa.Column('organization_name', sa.String(length=300), nullable=False),
    sa.Column('function_code', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('current_rate', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('proposed_rate', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('fot_effect_year', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_items_project_id'), 'project_items', ['project_id'], unique=False)
    op.create_table('tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.String(length=32), nullable=True),
    sa.Column('step_index', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('assignee_role', sa.String(length=32), nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.Column('municipality_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('last_reminder_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['municipality_id'], ['municipalities.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_run_id'), 'tasks', ['run_id'], unique=False)
    op.create_index('ix_tasks_status_due', 'tasks', ['status', 'due_date'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_to_telegram', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_tasks_status_due', table_name='tasks')
    op.drop_index(op.f('ix_tasks_run_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_project_items_project_id'), table_name='project_items')
    op.drop_table('project_items')
    op.drop_index(op.f('ix_generated_documents_project_id'), table_name='generated_documents')
    op.drop_table('generated_documents')
    op.drop_index(op.f('ix_projects_municipality_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_incoming_requests_organization_id'), table_name='incoming_requests')
    op.drop_table('incoming_requests')
    op.drop_table('users')
    op.drop_index('ix_staff_org_function', table_name='staff_positions')
    op.drop_table('staff_positions')
    op.drop_index(op.f('ix_enrollments_organization_id'), table_name='enrollments')
    op.drop_table('enrollments')
    op.drop_index(op.f('ix_buildings_organization_id'), table_name='buildings')
    op.drop_table('buildings')
    op.drop_index(op.f('ix_organizations_municipality_id'), table_name='organizations')
    op.drop_table('organizations')
    op.drop_table('norms')
    op.drop_index(op.f('ix_knowledge_chunks_document_id'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    op.drop_table('workflow_templates')
    op.drop_table('municipalities')
    op.drop_table('knowledge_documents')
    op.drop_index(op.f('ix_audit_log_created_at'), table_name='audit_log')
    op.drop_table('audit_log')
