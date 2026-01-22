"""Add revenue integration models

Revision ID: add_revenue_models
Revises: 7427e1ce0a16
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'add_revenue_models'
down_revision = '7427e1ce0a16'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table already exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    # Skip if tables already exist (created by db.create_all())
    if table_exists('revenue_imports'):
        print("Revenue tables already exist, skipping migration")
        return

    # Create revenue_imports table
    op.create_table('revenue_imports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=500), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False, default=0),
        sa.Column('new_months_added', sa.Integer(), default=0),
        sa.Column('records_updated', sa.Integer(), default=0),
        sa.Column('records_created', sa.Integer(), default=0),
        sa.Column('earliest_month', sa.Date(), nullable=True),
        sa.Column('latest_month', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create customer_revenue_data table
    op.create_table('customer_revenue_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=500), nullable=False),
        sa.Column('tpid', sa.String(length=50), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('bucket', sa.String(length=50), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('fiscal_month', sa.String(length=20), nullable=False),
        sa.Column('month_date', sa.Date(), nullable=False),
        sa.Column('revenue', sa.Float(), nullable=False, default=0.0),
        sa.Column('first_imported_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_import_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.ForeignKeyConstraint(['last_import_id'], ['revenue_imports.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('customer_name', 'bucket', 'month_date', name='uq_customer_bucket_month')
    )
    op.create_index('ix_customer_revenue_data_customer_id', 'customer_revenue_data', ['customer_id'], unique=False)
    op.create_index('ix_customer_revenue_data_customer_name', 'customer_revenue_data', ['customer_name'], unique=False)
    op.create_index('ix_customer_revenue_data_month_date', 'customer_revenue_data', ['month_date'], unique=False)
    op.create_index('ix_customer_revenue_data_tpid', 'customer_revenue_data', ['tpid'], unique=False)
    op.create_index('ix_revenue_data_lookup', 'customer_revenue_data', ['customer_name', 'bucket'], unique=False)

    # Create revenue_analyses table
    op.create_table('revenue_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=500), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('tpid', sa.String(length=50), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('bucket', sa.String(length=50), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(), nullable=False),
        sa.Column('months_analyzed', sa.Integer(), nullable=False),
        sa.Column('avg_revenue', sa.Float(), nullable=False),
        sa.Column('latest_revenue', sa.Float(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('recommended_action', sa.String(length=50), nullable=False),
        sa.Column('confidence', sa.String(length=20), nullable=False),
        sa.Column('priority_score', sa.Integer(), nullable=False),
        sa.Column('dollars_at_risk', sa.Float(), default=0.0),
        sa.Column('dollars_opportunity', sa.Float(), default=0.0),
        sa.Column('trend_slope', sa.Float(), default=0.0),
        sa.Column('last_month_change', sa.Float(), default=0.0),
        sa.Column('last_2month_change', sa.Float(), default=0.0),
        sa.Column('volatility_cv', sa.Float(), default=0.0),
        sa.Column('max_drawdown', sa.Float(), default=0.0),
        sa.Column('current_vs_max', sa.Float(), default=0.0),
        sa.Column('current_vs_avg', sa.Float(), default=0.0),
        sa.Column('engagement_rationale', sa.Text(), nullable=True),
        sa.Column('previous_category', sa.String(length=50), nullable=True),
        sa.Column('previous_priority_score', sa.Integer(), nullable=True),
        sa.Column('status_changed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('customer_name', 'bucket', name='uq_analysis_customer_bucket')
    )
    op.create_index('ix_revenue_analyses_customer_id', 'revenue_analyses', ['customer_id'], unique=False)
    op.create_index('ix_revenue_analyses_customer_name', 'revenue_analyses', ['customer_name'], unique=False)

    # Create revenue_config table
    op.create_table('revenue_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('min_revenue_for_outreach', sa.Integer(), default=3000),
        sa.Column('min_dollar_impact', sa.Integer(), default=1000),
        sa.Column('dollar_at_risk_override', sa.Integer(), default=2000),
        sa.Column('dollar_opportunity_override', sa.Integer(), default=1500),
        sa.Column('high_value_threshold', sa.Integer(), default=25000),
        sa.Column('strategic_threshold', sa.Integer(), default=50000),
        sa.Column('volatile_min_revenue', sa.Integer(), default=5000),
        sa.Column('recent_drop_threshold', sa.Float(), default=-0.15),
        sa.Column('expansion_growth_threshold', sa.Float(), default=0.08),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create revenue_engagements table
    op.create_table('revenue_engagements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('assigned_to_seller', sa.String(length=200), nullable=True),
        sa.Column('category_when_sent', sa.String(length=50), nullable=False),
        sa.Column('action_when_sent', sa.String(length=50), nullable=False),
        sa.Column('rationale_when_sent', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
        sa.Column('seller_response', sa.Text(), nullable=True),
        sa.Column('response_date', sa.DateTime(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('call_log_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['revenue_analyses.id'], ),
        sa.ForeignKeyConstraint(['call_log_id'], ['call_logs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('revenue_engagements')
    op.drop_table('revenue_config')
    op.drop_index('ix_revenue_analyses_customer_name', table_name='revenue_analyses')
    op.drop_index('ix_revenue_analyses_customer_id', table_name='revenue_analyses')
    op.drop_table('revenue_analyses')
    op.drop_index('ix_revenue_data_lookup', table_name='customer_revenue_data')
    op.drop_index('ix_customer_revenue_data_tpid', table_name='customer_revenue_data')
    op.drop_index('ix_customer_revenue_data_month_date', table_name='customer_revenue_data')
    op.drop_index('ix_customer_revenue_data_customer_name', table_name='customer_revenue_data')
    op.drop_index('ix_customer_revenue_data_customer_id', table_name='customer_revenue_data')
    op.drop_table('customer_revenue_data')
    op.drop_table('revenue_imports')
