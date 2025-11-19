"""Remove category column from verticals table

Revision ID: 2cd42a273210
Revises: 4f9cbf06d689
Create Date: 2025-11-19 17:38:45.593054

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2cd42a273210'
down_revision = '4f9cbf06d689'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the category column from verticals table
    op.drop_column('verticals', 'category')


def downgrade():
    # Add the category column back
    op.add_column('verticals', sa.Column('category', sa.String(200), nullable=True))
