"""remove ai quota system - drop ai_usage table and max_daily_calls_per_user column

Revision ID: 09adf0669d31
Revises: 
Create Date: 2025-11-24 10:11:51.149478

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '09adf0669d31'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Drop ai_usage table (if it exists)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'ai_usage' in inspector.get_table_names():
        op.drop_table('ai_usage')
    
    # Remove max_daily_calls_per_user column from ai_config (if it exists)
    if 'ai_config' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('ai_config')]
        if 'max_daily_calls_per_user' in columns:
            with op.batch_alter_table('ai_config', schema=None) as batch_op:
                batch_op.drop_column('max_daily_calls_per_user')


def downgrade():
    # Recreate max_daily_calls_per_user column
    with op.batch_alter_table('ai_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('max_daily_calls_per_user', sa.Integer(), nullable=True, server_default='20'))
    
    # Recreate ai_usage table
    op.create_table('ai_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('call_count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='unique_user_date')
    )
