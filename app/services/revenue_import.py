"""
Revenue Import Service
=====================
Handles importing MSXI revenue CSV data into the database.
Stores ALL customer data (not just flagged ones) to build historical records.

CSV Format (from MSXI):
Row 0: FiscalMonth, , FY26-Jul, FY26-Aug, ..., Total
Row 1: ServiceCompGrouping, TPAccountName, $ ACR, $ ACR, ...
Row 2+: Bucket, CustomerName, $revenue, $revenue, ...

Fiscal Month Format: "FY26-Jan" where FY26 = July 2025 - June 2026
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any
from io import StringIO, BytesIO

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore
    HAS_PANDAS = False

from app.models import (
    db, RevenueImport, CustomerRevenueData, Customer
)


class RevenueImportError(Exception):
    """Raised when import fails."""
    pass


def parse_currency(value) -> float:
    """Parse currency string to float.
    
    Handles: "$1,234.56", "$1234", "1234.56", etc.
    """
    if pd.isna(value) or value is None:
        return 0.0
    
    if isinstance(value, (int, float)):
        return float(value)
    
    # Remove currency symbols, commas, spaces
    cleaned = re.sub(r'[$,\s]', '', str(value))
    
    # Handle parentheses for negative numbers
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fiscal_month_to_date(fiscal_month: str) -> Optional[date]:
    """Convert fiscal month string to date (first of that month).
    
    Microsoft FY runs July-June:
    - FY26-Jul = July 2025 (FY26 starts July 2025)
    - FY26-Jan = January 2026
    - FY26-Jun = June 2026 (last month of FY26)
    
    Args:
        fiscal_month: String like "FY26-Jan"
        
    Returns:
        date object for first of that month, or None if invalid
    """
    match = re.match(r'FY(\d{2})-(\w{3})', fiscal_month)
    if not match:
        return None
    
    fy_num = int(match.group(1))
    month_abbr = match.group(2)
    
    # Map month abbreviation to number
    month_map = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    
    month_num = month_map.get(month_abbr)
    if not month_num:
        return None
    
    # Calculate calendar year
    # FY26 = July 2025 - June 2026
    # Jul-Dec are in year (FY - 1), Jan-Jun are in year FY
    base_year = 2000 + fy_num  # FY26 -> 2026
    
    if month_num >= 7:  # Jul-Dec
        calendar_year = base_year - 1
    else:  # Jan-Jun
        calendar_year = base_year
    
    return date(calendar_year, month_num, 1)


def date_to_fiscal_month(d: date) -> str:
    """Convert date to fiscal month string.
    
    Args:
        d: date object
        
    Returns:
        String like "FY26-Jan"
    """
    month_abbrs = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    # Calculate fiscal year
    # Jul-Dec: FY is year + 1
    # Jan-Jun: FY is year
    if d.month >= 7:
        fy = d.year + 1 - 2000  # 2025 July -> FY26
    else:
        fy = d.year - 2000  # 2026 January -> FY26
    
    return f"FY{fy:02d}-{month_abbrs[d.month - 1]}"


def load_csv(file_content: bytes | str, filename: str = "upload.csv") -> Any:
    """Load CSV content into a DataFrame.
    
    Handles various encodings common in MSXI exports.
    
    Args:
        file_content: Raw bytes or string content of the CSV
        filename: Original filename for error messages
        
    Returns:
        DataFrame with raw CSV data
    """
    if not HAS_PANDAS:
        raise RevenueImportError("pandas is required for revenue import. Install with: pip install pandas")
    
    # If bytes, try various encodings
    encodings = ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']
    
    if isinstance(file_content, bytes):
        for encoding in encodings:
            try:
                content = file_content.decode(encoding)
                return pd.read_csv(StringIO(content), header=None)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise RevenueImportError(f"Could not read CSV with any supported encoding: {filename}")
    else:
        return pd.read_csv(StringIO(file_content), header=None)


def process_csv(df: Any) -> tuple[Any, list[str]]:
    """Process raw DataFrame to extract structured data.
    
    Args:
        df: Raw DataFrame (pandas) from CSV
        
    Returns:
        Tuple of (processed DataFrame, list of month column names)
    """
    # Get month columns from row 0
    month_row = df.iloc[0].tolist()
    month_cols = [str(m) for m in month_row[2:-1] if pd.notna(m) and 'FY' in str(m)]
    
    if not month_cols:
        raise RevenueImportError("No fiscal month columns found (expecting FYxx-Mon format)")
    
    # Build column names
    num_cols = len(df.columns)
    col_names = ['ServiceCompGrouping', 'TPAccountName'] + month_cols + ['Total']
    
    # Adjust if column count doesn't match
    if len(col_names) != num_cols:
        col_names = ['ServiceCompGrouping', 'TPAccountName']
        for i, m in enumerate(month_row[2:]):
            if pd.notna(m) and str(m) != 'nan':
                if 'FY' in str(m):
                    col_names.append(str(m))
                elif str(m).lower() == 'total':
                    col_names.append('Total')
                else:
                    col_names.append(f'Col_{i}')
            else:
                col_names.append(f'Col_{i}')
        while len(col_names) < num_cols:
            col_names.append(f'Extra_{len(col_names)}')
        col_names = col_names[:num_cols]
    
    df.columns = col_names
    
    # Skip header rows (row 0 = month names, row 1 = column labels)
    df = df.iloc[2:].copy()
    
    # Refresh month columns from actual column names
    month_cols = [c for c in df.columns if 'FY' in str(c)]
    
    # Filter out empty rows and totals
    df = df[df['ServiceCompGrouping'].notna()]
    df = df[~df['TPAccountName'].isin(['Total', '', None])]
    df = df[df['TPAccountName'].notna()]
    df = df.reset_index(drop=True)
    
    return df, month_cols


def import_revenue_csv(
    file_content: bytes | str,
    filename: str,
    user_id: int,
    territory_alignments: Optional[dict] = None
) -> RevenueImport:
    """Import revenue data from CSV into the database.
    
    This stores ALL customer/month data, not just flagged ones.
    Uses upsert logic: updates existing records, creates new ones.
    
    Args:
        file_content: Raw CSV content
        filename: Original filename
        user_id: ID of user performing import
        territory_alignments: Optional dict mapping (customer_name, bucket) -> seller_name
        
    Returns:
        RevenueImport record with import stats
    """
    # Load and process CSV
    df = load_csv(file_content, filename)
    df, month_cols = process_csv(df)
    
    if df.empty:
        raise RevenueImportError("No data rows found in CSV")
    
    # Convert month columns to dates
    month_dates = {}
    for mc in month_cols:
        d = fiscal_month_to_date(mc)
        if d:
            month_dates[mc] = d
    
    if not month_dates:
        raise RevenueImportError("Could not parse any fiscal month columns")
    
    # Create import record
    earliest = min(month_dates.values())
    latest = max(month_dates.values())
    
    import_record = RevenueImport(
        filename=filename,
        user_id=user_id,
        record_count=len(df),
        earliest_month=earliest,
        latest_month=latest
    )
    db.session.add(import_record)
    db.session.flush()  # Get the ID
    
    # Track stats
    records_created = 0
    records_updated = 0
    new_months = set()
    
    # Process each row
    for _, row in df.iterrows():
        bucket = str(row['ServiceCompGrouping']).strip()
        customer_name = str(row['TPAccountName']).strip()
        
        if not customer_name or customer_name.lower() == 'total':
            continue
        
        # Get seller from territory alignments if provided
        seller_name = None
        if territory_alignments:
            seller_name = territory_alignments.get((customer_name, bucket))
        
        # Try to match to existing NoteHelper customer
        customer_id = None
        customer = Customer.query.filter(
            db.func.lower(Customer.name) == customer_name.lower()
        ).first()
        if customer:
            customer_id = customer.id
        
        # Process each month column
        for month_col, month_date in month_dates.items():
            revenue = parse_currency(row.get(month_col, 0))
            fiscal_month = month_col
            
            # Check if record exists (upsert logic)
            existing = CustomerRevenueData.query.filter_by(
                customer_name=customer_name,
                bucket=bucket,
                month_date=month_date
            ).first()
            
            if existing:
                # Update if value changed
                if existing.revenue != revenue:
                    existing.revenue = revenue
                    existing.last_updated_at = datetime.utcnow()
                    existing.last_import_id = import_record.id
                    records_updated += 1
                # Update customer_id if we now have a match
                if customer_id and not existing.customer_id:
                    existing.customer_id = customer_id
                # Update seller if we now have alignment
                if seller_name and not existing.seller_name:
                    existing.seller_name = seller_name
            else:
                # Create new record
                new_record = CustomerRevenueData(
                    customer_name=customer_name,
                    bucket=bucket,
                    customer_id=customer_id,
                    seller_name=seller_name,
                    fiscal_month=fiscal_month,
                    month_date=month_date,
                    revenue=revenue,
                    last_import_id=import_record.id
                )
                db.session.add(new_record)
                records_created += 1
                
                # Track if this is a new month we've never seen
                existing_months = db.session.query(
                    CustomerRevenueData.month_date
                ).filter(
                    CustomerRevenueData.month_date == month_date,
                    CustomerRevenueData.id != new_record.id
                ).first()
                if not existing_months:
                    new_months.add(month_date)
    
    # Update import stats
    import_record.records_created = records_created
    import_record.records_updated = records_updated
    import_record.new_months_added = len(new_months)
    
    db.session.commit()
    
    return import_record


def load_territory_alignments(file_content: bytes | str) -> dict:
    """Load territory alignments CSV to map customers to sellers.
    
    Expected format: CSV with columns including TPID, customer name, seller alias
    
    Args:
        file_content: Raw CSV content
        
    Returns:
        Dict mapping (customer_name, bucket) -> seller_name
    """
    if pd is None:
        return {}
    
    try:
        if isinstance(file_content, bytes):
            df = pd.read_csv(BytesIO(file_content))
        else:
            df = pd.read_csv(StringIO(file_content))
        
        alignments = {}
        # This is a placeholder - actual column names depend on the territory file format
        # We'll need to adapt this based on the actual file structure
        
        return alignments
    except Exception:
        return {}


def get_import_history(limit: int = 20) -> list[RevenueImport]:
    """Get recent import history.
    
    Args:
        limit: Max number of imports to return
        
    Returns:
        List of RevenueImport records, most recent first
    """
    return RevenueImport.query.order_by(
        RevenueImport.imported_at.desc()
    ).limit(limit).all()


def get_months_in_database() -> list[dict]:
    """Get all unique months in the database with record counts.
    
    Returns:
        List of dicts with month_date, fiscal_month, record_count
    """
    results = db.session.query(
        CustomerRevenueData.month_date,
        CustomerRevenueData.fiscal_month,
        db.func.count(CustomerRevenueData.id).label('record_count')
    ).group_by(
        CustomerRevenueData.month_date
    ).order_by(
        CustomerRevenueData.month_date.desc()
    ).all()
    
    return [
        {
            'month_date': r.month_date,
            'fiscal_month': r.fiscal_month,
            'record_count': r.record_count
        }
        for r in results
    ]


def get_customer_revenue_history(
    customer_name: str,
    bucket: Optional[str] = None
) -> list[CustomerRevenueData]:
    """Get revenue history for a specific customer.
    
    Args:
        customer_name: Customer name to look up
        bucket: Optional bucket filter (Core DBs, Analytics, Modern DBs)
        
    Returns:
        List of CustomerRevenueData records ordered by month
    """
    query = CustomerRevenueData.query.filter_by(customer_name=customer_name)
    
    if bucket:
        query = query.filter_by(bucket=bucket)
    
    return query.order_by(CustomerRevenueData.month_date).all()
