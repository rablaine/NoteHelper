"""add performance indexes for frequently queried columns

Revision ID: a437b6017a94
Revises: 7cb5672ce31a
Create Date: 2025-11-20 23:55:18.399445

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a437b6017a94'
down_revision = '7cb5672ce31a'
branch_labels = None
depends_on = None


def upgrade():
    # Call logs - most frequently queried table
    op.create_index('idx_call_logs_user_id', 'call_logs', ['user_id'])
    op.create_index('idx_call_logs_customer_id', 'call_logs', ['customer_id'])
    op.create_index('idx_call_logs_call_date', 'call_logs', ['call_date'])
    op.create_index('idx_call_logs_user_date', 'call_logs', ['user_id', 'call_date'])  # Composite for sorted lists
    
    # Customers - frequently filtered and joined
    op.create_index('idx_customers_user_id', 'customers', ['user_id'])
    op.create_index('idx_customers_name', 'customers', ['name'])  # For alphabetical sorting
    
    # Sellers - frequently joined with customers and territories
    op.create_index('idx_sellers_user_id', 'sellers', ['user_id'])
    
    # Territories - frequently joined
    op.create_index('idx_territories_user_id', 'territories', ['user_id'])
    op.create_index('idx_territories_pod_id', 'territories', ['pod_id'])
    
    # Topics - frequently filtered and sorted
    op.create_index('idx_topics_user_id', 'topics', ['user_id'])
    op.create_index('idx_topics_name', 'topics', ['name'])  # For alphabetical sorting
    
    # PODs - frequently joined with territories
    op.create_index('idx_pods_user_id', 'pods', ['user_id'])
    
    # Solution Engineers - frequently joined with PODs
    op.create_index('idx_solution_engineers_user_id', 'solution_engineers', ['user_id'])
    
    # Verticals - frequently joined with customers
    op.create_index('idx_verticals_user_id', 'verticals', ['user_id'])
    
    # AI Usage - frequently queried by user and date
    op.create_index('idx_ai_usage_user_date', 'ai_usage', ['user_id', 'date'])
    
    # AI Query Log - frequently queried by user and timestamp
    op.create_index('idx_ai_query_log_user_id', 'ai_query_log', ['user_id'])
    op.create_index('idx_ai_query_log_timestamp', 'ai_query_log', ['timestamp'])


def downgrade():
    # Drop indexes in reverse order
    op.drop_index('idx_ai_query_log_timestamp')
    op.drop_index('idx_ai_query_log_user_id')
    op.drop_index('idx_ai_usage_user_date')
    op.drop_index('idx_verticals_user_id')
    op.drop_index('idx_solution_engineers_user_id')
    op.drop_index('idx_pods_user_id')
    op.drop_index('idx_topics_name')
    op.drop_index('idx_topics_user_id')
    op.drop_index('idx_territories_pod_id')
    op.drop_index('idx_territories_user_id')
    op.drop_index('idx_sellers_user_id')
    op.drop_index('idx_customers_name')
    op.drop_index('idx_customers_user_id')
    op.drop_index('idx_call_logs_user_date')
    op.drop_index('idx_call_logs_call_date')
    op.drop_index('idx_call_logs_customer_id')
    op.drop_index('idx_call_logs_user_id')
