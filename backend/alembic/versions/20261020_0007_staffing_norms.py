"""staffing norms

Нормативная численность АУП и вспомогательного персонала: группы нормирования,
агрегированная штатка и занятость без ФИО, показатели учреждений, нормативы с
документами-основаниями, результаты расчёта и их связь с заявками.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20 18:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'personnel_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('top_category', sa.String(length=16), nullable=False),
        sa.Column('subcategory', sa.String(length=40), nullable=True),
        sa.Column('institution_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('positions', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_table(
        'normative_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('number', sa.String(length=60), nullable=True),
        sa.Column('issued_at', sa.Date(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('issuer', sa.String(length=300), nullable=True),
        sa.Column('scope_level', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('source_ref', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'normative_coefficients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('personnel_group_id', sa.Integer(), nullable=False),
        sa.Column('institution_type', sa.String(length=16), nullable=False),
        sa.Column('scope_level', sa.String(length=16), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=True),
        sa.Column('metric', sa.String(length=32), nullable=False),
        sa.Column('unit_size', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('fte_per_unit', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('min_fte', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('max_fte', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('applies_from', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('applies_to', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('rounding_step', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('rounding_mode', sa.String(length=8), nullable=False),
        sa.Column('tolerance_abs', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('tolerance_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['normative_documents.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['personnel_group_id'], ['personnel_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_normative_coefficients_document_id'), 'normative_coefficients', ['document_id'], unique=False)
    op.create_index(op.f('ix_normative_coefficients_personnel_group_id'), 'normative_coefficients', ['personnel_group_id'], unique=False)

    op.create_table(
        'staffing_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.String(length=9), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['normative_documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_staffing_schedules_organization_id'), 'staffing_schedules', ['organization_id'], unique=False)
    op.create_index('ux_staffing_schedule', 'staffing_schedules', ['organization_id', 'academic_year'], unique=True)

    op.create_table(
        'staffing_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=False),
        sa.Column('personnel_group_id', sa.Integer(), nullable=False),
        sa.Column('building_id', sa.Integer(), nullable=True),
        sa.Column('approved_fte', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('occupied_fte', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['personnel_group_id'], ['personnel_groups.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['schedule_id'], ['staffing_schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_staffing_lines_schedule_id'), 'staffing_lines', ['schedule_id'], unique=False)

    op.create_table(
        'institution_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.String(length=9), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('students_count', sa.Integer(), nullable=True),
        sa.Column('classes_count', sa.Integer(), nullable=True),
        sa.Column('groups_count', sa.Integer(), nullable=True),
        sa.Column('total_area_m2', sa.Numeric(precision=10, scale=1), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_institution_metrics_organization_id'), 'institution_metrics', ['organization_id'], unique=False)
    op.create_index('ux_institution_metrics', 'institution_metrics', ['organization_id', 'academic_year'], unique=True)

    op.create_table(
        'staffing_analysis_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('personnel_group_id', sa.Integer(), nullable=True),
        sa.Column('top_category', sa.String(length=16), nullable=False),
        sa.Column('academic_year', sa.String(length=9), nullable=False),
        sa.Column('period_date', sa.Date(), nullable=False),
        sa.Column('basis', sa.String(length=16), nullable=False),
        sa.Column('required_fte', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('approved_fte', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('occupied_fte', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('fact_fte', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('deviation_fte', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('deviation_pct', sa.Numeric(precision=8, scale=1), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('severity', sa.String(length=8), nullable=True),
        sa.Column('missing_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('coefficients_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metrics_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['personnel_group_id'], ['personnel_groups.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_staffing_analysis_results_organization_id'), 'staffing_analysis_results', ['organization_id'], unique=False)
    op.create_index('ix_staffing_results_current', 'staffing_analysis_results', ['academic_year', 'is_current', 'basis', 'top_category'], unique=False)

    op.create_table(
        'request_staffing_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('analysis_result_id', sa.Integer(), nullable=False),
        sa.Column('link_type', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.String(length=8), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_result_id'], ['staffing_analysis_results.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_id'], ['incoming_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_request_staffing_links_analysis_result_id'), 'request_staffing_links', ['analysis_result_id'], unique=False)
    op.create_index(op.f('ix_request_staffing_links_request_id'), 'request_staffing_links', ['request_id'], unique=False)


def downgrade() -> None:
    for table in ('request_staffing_links', 'staffing_analysis_results', 'institution_metrics',
                  'staffing_lines', 'staffing_schedules', 'normative_coefficients',
                  'normative_documents', 'personnel_groups'):
        op.drop_table(table)
