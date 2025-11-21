"""add microsoft_email and external_email to users

Revision ID: f9035c1c9285
Revises: a437b6017a94
Create Date: 2025-11-21 16:25:50.016787

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9035c1c9285'
down_revision = 'a437b6017a94'
branch_labels = None
depends_on = None


def upgrade():
    # Add microsoft_email and external_email columns to users table
    op.add_column('users', sa.Column('microsoft_email', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('external_email', sa.String(length=255), nullable=True))


def downgrade():
    # Remove the email columns
    op.drop_column('users', 'external_email')
    op.drop_column('users', 'microsoft_email')
