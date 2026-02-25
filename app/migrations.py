"""
Idempotent database migrations for NoteHelper.

This module provides safe, repeatable schema migrations that can run on every
deployment without risk of data loss. Each migration checks if it needs to run
before making changes.

Usage:
    from app.migrations import run_migrations
    run_migrations(db)

Guidelines for adding new migrations:
1. Always check if the change is needed before applying (idempotent)
2. Use inspector.get_columns() to check for existing columns
3. Use inspector.get_table_names() to check for existing tables
4. Never use DROP TABLE or DROP COLUMN without explicit user confirmation
5. Add a descriptive print statement so deploy logs show what happened
"""
from sqlalchemy import inspect, text


def run_migrations(db):
    """
    Run all idempotent schema migrations.
    
    Safe to run multiple times - only applies changes that haven't been made yet.
    This replaces Flask-Migrate/Alembic for simpler, safer deployments.
    
    Args:
        db: SQLAlchemy database instance
    """
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    
    print("Running idempotent migrations...")
    
    # =========================================================================
    # Add new migrations below this line
    # =========================================================================
    
    # Migration: Upgrade milestones table for MSX integration
    _migrate_milestones_for_msx(db, inspector)
    
    # Migration: Upgrade call_date from Date to DateTime for meeting timestamps
    _migrate_call_date_to_datetime(db, inspector)
    
    # =========================================================================
    # End migrations
    # =========================================================================
    
    print("Migrations complete!")


def _add_column_if_not_exists(db, inspector, table: str, column: str, column_def: str):
    """
    Add a column to a table if it doesn't already exist.
    
    Args:
        db: SQLAlchemy database instance
        inspector: SQLAlchemy inspector instance
        table: Name of the table to modify
        column: Name of the column to add
        column_def: SQL column definition (e.g., 'TEXT', 'INTEGER DEFAULT 0')
    
    Example:
        _add_column_if_not_exists(db, inspector, 'customers', 'priority', 'INTEGER DEFAULT 0')
    """
    columns = [c['name'] for c in inspector.get_columns(table)]
    if column not in columns:
        with db.engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
            conn.commit()
        print(f"  Added column '{column}' to '{table}'")
    else:
        print(f"  Column '{column}' already exists in '{table}' - skipping")


def _add_index_if_not_exists(db, inspector, table: str, index_name: str, columns: list):
    """
    Add an index to a table if it doesn't already exist.
    
    Args:
        db: SQLAlchemy database instance
        inspector: SQLAlchemy inspector instance
        table: Name of the table
        index_name: Name for the index
        columns: List of column names to index
    
    Example:
        _add_index_if_not_exists(db, inspector, 'call_logs', 'ix_call_logs_date', ['call_date'])
    """
    existing_indexes = [idx['name'] for idx in inspector.get_indexes(table)]
    if index_name not in existing_indexes:
        cols = ', '.join(columns)
        with db.engine.connect() as conn:
            conn.execute(text(f"CREATE INDEX {index_name} ON {table} ({cols})"))
            conn.commit()
        print(f"  Added index '{index_name}' on '{table}'")
    else:
        print(f"  Index '{index_name}' already exists - skipping")


def _table_exists(inspector, table: str) -> bool:
    """Check if a table exists in the database."""
    return table in inspector.get_table_names()


def _column_exists(inspector, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    columns = [c['name'] for c in inspector.get_columns(table)]
    return column in columns


def _migrate_milestones_for_msx(db, inspector):
    """
    Migrate milestones table for MSX integration.
    
    This migration:
    1. Drops and recreates milestones table with new schema (SQLite limitation)
    2. Creates msx_tasks table
    
    Note: SQLite can't ALTER TABLE to add UNIQUE columns, so we recreate the table.
    Milestone data is cleared - will be re-created via MSX picker.
    """
    # Check if migration is needed by looking for new columns
    if _table_exists(inspector, 'milestones'):
        if not _column_exists(inspector, 'milestones', 'msx_milestone_id'):
            print("  Migrating milestones table for MSX integration...")
            
            with db.engine.connect() as conn:
                # Clear junction table first (foreign keys)
                conn.execute(text("DELETE FROM call_logs_milestones"))
                # SQLite can't add UNIQUE column via ALTER TABLE, so drop and recreate
                conn.execute(text("DROP TABLE milestones"))
                conn.execute(text("""
                    CREATE TABLE milestones (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        msx_milestone_id VARCHAR(50) UNIQUE,
                        milestone_number VARCHAR(50),
                        url VARCHAR(2000) NOT NULL,
                        title VARCHAR(500),
                        msx_status VARCHAR(50),
                        msx_status_code INTEGER,
                        opportunity_name VARCHAR(500),
                        customer_id INTEGER REFERENCES customers(id),
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                """))
                conn.commit()
            print("    Recreated milestones table with MSX schema")
        else:
            print("  Milestones already migrated for MSX - skipping")
    
    # Create msx_tasks table if it doesn't exist
    if not _table_exists(inspector, 'msx_tasks'):
        print("  Creating msx_tasks table...")
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE msx_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msx_task_id VARCHAR(50) NOT NULL UNIQUE,
                    msx_task_url VARCHAR(2000),
                    subject VARCHAR(500) NOT NULL,
                    description TEXT,
                    task_category INTEGER NOT NULL,
                    task_category_name VARCHAR(100),
                    duration_minutes INTEGER DEFAULT 60 NOT NULL,
                    is_hok BOOLEAN DEFAULT 0 NOT NULL,
                    call_log_id INTEGER NOT NULL REFERENCES call_logs(id),
                    milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """))
            conn.commit()
        print("    Created msx_tasks table")
    else:
        print("  msx_tasks table already exists - skipping")


def _migrate_call_date_to_datetime(db, inspector):
    """
    Upgrade call_date column from Date to DateTime for meeting timestamps.
    
    SQLite stores DATE as TEXT 'YYYY-MM-DD' and DATETIME as 'YYYY-MM-DD HH:MM:SS'.
    This migration:
    1. Adds a temporary call_datetime column
    2. Copies data with time conversion
    3. Drops old column and renames new one via table rebuild (SQLite limitation)
    
    Idempotent: Checks column type before running. Safe if already DateTime.
    """
    if not _table_exists(inspector, 'call_logs'):
        return
    
    # Check if call_date is already DateTime by inspecting column type
    columns = {c['name']: c for c in inspector.get_columns('call_logs')}
    if 'call_date' not in columns:
        return
    
    col_type = str(columns['call_date']['type']).upper()
    
    # If it's already DATETIME, skip
    if 'DATETIME' in col_type:
        print("  call_date is already DateTime - skipping")
        return
    
    print("  Upgrading call_date from Date to DateTime...")
    
    with db.engine.connect() as conn:
        # Step 1: Add temporary datetime column
        conn.execute(text("ALTER TABLE call_logs ADD COLUMN call_datetime DATETIME"))
        
        # Step 2: Copy and convert data
        # Handles various date formats safely
        conn.execute(text("""
            UPDATE call_logs 
            SET call_datetime = CASE
                WHEN call_date LIKE '____-__-__ %' THEN call_date
                WHEN call_date LIKE '____-__-__T%' THEN REPLACE(call_date, 'T', ' ')
                WHEN call_date LIKE '____-__-__' THEN call_date || ' 00:00:00'
                ELSE call_date || '-01-01 00:00:00'
            END
        """))
        
        # Step 3: Rebuild table with new column type (SQLite can't ALTER COLUMN)
        # Get all current columns except call_date and call_datetime
        all_cols = [c['name'] for c in inspector.get_columns('call_logs') 
                    if c['name'] not in ('call_date', 'call_datetime')]
        
        # Build column list for copy
        cols_csv = ', '.join(all_cols)
        
        conn.execute(text("ALTER TABLE call_logs RENAME TO call_logs_backup"))
        
        # Get the CREATE TABLE statement and modify it
        result = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='call_logs_backup'"
        ))
        create_sql = result.scalar()
        
        # Replace table name and fix the column type
        create_sql = create_sql.replace('call_logs_backup', 'call_logs', 1)
        # Replace DATE with DATETIME for call_date column
        create_sql = create_sql.replace(
            'call_date DATE NOT NULL', 
            'call_date DATETIME NOT NULL'
        )
        # Also handle if it was defined without explicit type keyword
        create_sql = create_sql.replace(
            'call_date DATE', 
            'call_date DATETIME'
        )
        
        conn.execute(text(create_sql))
        
        # Copy data back, using call_datetime for the call_date column
        conn.execute(text(f"""
            INSERT INTO call_logs ({cols_csv}, call_date)
            SELECT {cols_csv}, call_datetime FROM call_logs_backup
        """))
        
        conn.execute(text("DROP TABLE call_logs_backup"))
        conn.commit()
    
    print("    Upgraded call_date to DateTime successfully")