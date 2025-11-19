"""Change call_date from datetime to date

Revision ID: 4f9cbf06d689
Revises: 3620d38a767d
Create Date: 2025-11-19 17:29:02.036902

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f9cbf06d689'
down_revision = '3620d38a767d'
branch_labels = None
depends_on = None


def upgrade():
    # Convert call_date from TIMESTAMP to DATE by casting and removing time component
    op.execute('ALTER TABLE call_logs ALTER COLUMN call_date TYPE DATE USING call_date::date')


def downgrade():
    # Convert call_date from DATE back to TIMESTAMP (will default to midnight)
    op.execute('ALTER TABLE call_logs ALTER COLUMN call_date TYPE TIMESTAMP USING call_date::timestamp')
