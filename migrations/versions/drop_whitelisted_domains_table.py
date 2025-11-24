"""drop whitelisted_domains table

Revision ID: drop_whitelist
Revises: 09adf0669d31
Create Date: 2025-11-24 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'drop_whitelist'
down_revision = '09adf0669d31'
branch_labels = None
depends_on = None


def upgrade():
    # Drop whitelisted_domains table (not needed in single-user mode)
    # Check if table exists first (for fresh SQLite databases)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'whitelisted_domains' in inspector.get_table_names():
        op.drop_table('whitelisted_domains')


def downgrade():
    # Recreate whitelisted_domains table
    op.create_table('whitelisted_domains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain')
    )
