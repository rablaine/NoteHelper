"""Convert datetime columns to timezone-aware

Revision ID: 02c4bb8d32a4
Revises: f8128ba331bb
Create Date: 2025-11-18 12:40:22.854637

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '02c4bb8d32a4'
down_revision = 'f8128ba331bb'
branch_labels = None
depends_on = None


def upgrade():
    # Convert all datetime columns from TIMESTAMP to TIMESTAMPTZ
    # PostgreSQL will interpret existing naive timestamps as being in the server's timezone
    # and convert them properly
    
    # Call logs
    op.execute("ALTER TABLE call_logs ALTER COLUMN call_date TYPE TIMESTAMP WITH TIME ZONE USING call_date AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE call_logs ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE call_logs ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC'")
    
    # Territories
    op.execute("ALTER TABLE territories ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC'")
    
    # Sellers
    op.execute("ALTER TABLE sellers ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC'")
    
    # Customers
    op.execute("ALTER TABLE customers ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC'")
    
    # Topics
    op.execute("ALTER TABLE topics ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC'")


def downgrade():
    # Convert back to TIMESTAMP WITHOUT TIME ZONE
    op.execute("ALTER TABLE call_logs ALTER COLUMN call_date TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE call_logs ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE call_logs ALTER COLUMN updated_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    
    op.execute("ALTER TABLE territories ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE sellers ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE customers ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE topics ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE")
