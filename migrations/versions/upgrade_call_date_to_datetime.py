"""Upgrade call_date from Date to DateTime for meeting timestamps

Revision ID: call_date_datetime
Revises: b3c50a3227d4
Create Date: 2026-02-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'call_date_datetime'
down_revision = 'b3c50a3227d4'
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade call_date from Date to DateTime.
    
    SQLite stores DATE as TEXT in format 'YYYY-MM-DD'.
    SQLite stores DATETIME as TEXT in format 'YYYY-MM-DD HH:MM:SS.SSSSSS'.
    
    We need to manually convert because SQLite batch_alter_table doesn't
    properly handle Date->DateTime conversion.
    
    Strategy:
    1. Add a new call_datetime column
    2. Copy data with time appended
    3. Drop old column and rename new one
    """
    conn = op.get_bind()
    
    # Step 1: Add new column
    op.add_column('call_logs', sa.Column('call_datetime', sa.DateTime(), nullable=True))
    
    # Step 2: Copy and convert data - append midnight time to existing dates
    # Handle both 'YYYY-MM-DD' format and potential ISO format with T
    conn.execute(text("""
        UPDATE call_logs 
        SET call_datetime = CASE
            WHEN call_date LIKE '____-__-__ %' THEN call_date
            WHEN call_date LIKE '____-__-__T%' THEN REPLACE(call_date, 'T', ' ')
            WHEN call_date LIKE '____-__-__' THEN call_date || ' 00:00:00'
            ELSE call_date || '-01-01 00:00:00'
        END
    """))
    
    # Step 3: Use batch mode to drop old and rename new
    with op.batch_alter_table('call_logs', schema=None) as batch_op:
        batch_op.drop_column('call_date')
        batch_op.alter_column('call_datetime', new_column_name='call_date', nullable=False)


def downgrade():
    """Downgrade DateTime back to Date.
    
    Warning: This will lose time information from meeting imports.
    """
    conn = op.get_bind()
    
    # Step 1: Add new date column
    op.add_column('call_logs', sa.Column('call_date_only', sa.Date(), nullable=True))
    
    # Step 2: Copy just the date part
    conn.execute(text("""
        UPDATE call_logs 
        SET call_date_only = DATE(call_date)
    """))
    
    # Step 3: Drop datetime column and rename date column
    with op.batch_alter_table('call_logs', schema=None) as batch_op:
        batch_op.drop_column('call_date')
        batch_op.alter_column('call_date_only', new_column_name='call_date', nullable=False)
