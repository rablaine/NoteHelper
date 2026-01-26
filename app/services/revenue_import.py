"""
Revenue Import Service
=====================
Handles importing MSXI revenue CSV data into the database.
Stores ALL customer data (not just flagged ones) to build historical records.

CSV Format (from MSXI ACR Details by Quarter Month SL4):
Row 0: FiscalMonth, , , FY26-Jul, FY26-Aug, ..., Total
Row 1: TPAccountName, ServiceCompGrouping, ServiceLevel4, $ ACR, $ ACR, ...
Row 2+: CustomerName, Bucket, Product, $revenue, $revenue, ...

Where:
- Bucket = "Total" means customer total across all buckets
- Bucket = "Analytics"/"Core DBs"/etc with Product = "Total" means bucket total
- Bucket = "Analytics"/"Core DBs"/etc with Product = specific name means product detail

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
    db, RevenueImport, CustomerRevenueData, ProductRevenueData, Customer
)


# Product consolidation rules - products starting with these prefixes get rolled up
PRODUCT_CONSOLIDATION_PREFIXES = [
    'Azure Synapse Analytics',
]


def consolidate_product_name(product: str) -> str:
    """Get the consolidated product name for display purposes.
    
    Products starting with certain prefixes (like 'Azure Synapse Analytics')
    get consolidated into a single display name.
    
    Args:
        product: Original product name
        
    Returns:
        Consolidated product name (or original if no consolidation applies)
    """
    for prefix in PRODUCT_CONSOLIDATION_PREFIXES:
        if product.startswith(prefix):
            return prefix
    return product


def consolidate_products_list(products: list[dict]) -> list[dict]:
    """Consolidate a list of product dicts by rolling up matching prefixes.
    
    Products starting with consolidation prefixes get merged into a single entry
    with summed revenues and customer counts.
    
    Args:
        products: List of dicts with 'product', 'customer_count', 'total_revenue'
        
    Returns:
        Consolidated list with rolled-up products
    """
    consolidated = {}
    
    for p in products:
        display_name = consolidate_product_name(p['product'])
        
        if display_name not in consolidated:
            consolidated[display_name] = {
                'product': display_name,
                'customer_count': 0,
                'total_revenue': 0,
                '_original_products': []
            }
        
        # For customer count, we need to be careful not to double-count
        # if multiple sub-products have the same customer
        consolidated[display_name]['total_revenue'] += p.get('total_revenue', 0)
        consolidated[display_name]['_original_products'].append(p['product'])
        # Note: customer_count may over-count if same customer uses multiple sub-products
        # For now, we'll use the max of the individual counts as a rough estimate
        consolidated[display_name]['customer_count'] = max(
            consolidated[display_name]['customer_count'],
            p.get('customer_count', 0)
        )
    
    return list(consolidated.values())


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
    
    New format (ACR Details by Quarter Month SL4):
    Row 0: FiscalMonth, , , FY26-Jul, FY26-Aug, ..., Total
    Row 1: TPAccountName, ServiceCompGrouping, ServiceLevel4, $ ACR, ...
    
    Args:
        df: Raw DataFrame (pandas) from CSV
        
    Returns:
        Tuple of (processed DataFrame, list of month column names)
    """
    # Get month columns from row 0 (starts at column 3 in new format)
    month_row = df.iloc[0].tolist()
    
    # Find where month columns start (look for FY pattern)
    month_start_idx = None
    for i, val in enumerate(month_row):
        if pd.notna(val) and 'FY' in str(val):
            month_start_idx = i
            break
    
    if month_start_idx is None:
        raise RevenueImportError("No fiscal month columns found (expecting FYxx-Mon format)")
    
    # Extract month columns (everything from first FY column to "Total" or end)
    month_cols = []
    for val in month_row[month_start_idx:]:
        if pd.notna(val):
            val_str = str(val).strip()
            if 'FY' in val_str:
                month_cols.append(val_str)
            elif val_str.lower() == 'total':
                break  # Stop at Total column
    
    if not month_cols:
        raise RevenueImportError("No fiscal month columns found")
    
    # Build column names based on new format
    # Columns: TPAccountName, ServiceCompGrouping, ServiceLevel4, [months...], Total
    col_names = ['TPAccountName', 'ServiceCompGrouping', 'ServiceLevel4'] + month_cols + ['Total']
    
    # Pad if needed
    while len(col_names) < len(df.columns):
        col_names.append(f'Extra_{len(col_names)}')
    col_names = col_names[:len(df.columns)]
    
    df.columns = col_names
    
    # Skip header rows (row 0 = month names, row 1 = column labels)
    df = df.iloc[2:].copy()
    
    # Filter out empty rows
    df = df[df['TPAccountName'].notna()]
    df = df[df['TPAccountName'] != '']
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
    
    New format handles:
    - Bucket totals (ServiceLevel4 = "Total") -> CustomerRevenueData (for analysis)
    - Product details (ServiceLevel4 = product name) -> ProductRevenueData (for drill-down)
    - Customer totals (ServiceCompGrouping = "Total") -> skipped (can be calculated)
    
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
    bucket_records_created = 0
    bucket_records_updated = 0
    product_records_created = 0
    product_records_updated = 0
    new_months = set()
    
    # Build a lookup of existing NoteHelper customers
    customer_lookup = {}
    for customer in Customer.query.all():
        customer_lookup[customer.name.lower()] = customer.id
        if customer.nickname:
            customer_lookup[customer.nickname.lower()] = customer.id
    
    # Process each row
    for _, row in df.iterrows():
        customer_name = str(row['TPAccountName']).strip()
        bucket = str(row['ServiceCompGrouping']).strip() if pd.notna(row.get('ServiceCompGrouping')) else ''
        product = str(row['ServiceLevel4']).strip() if pd.notna(row.get('ServiceLevel4')) else ''
        
        if not customer_name:
            continue
        
        # Skip customer total rows (bucket = "Total")
        if bucket.lower() == 'total':
            continue
        
        # Try to match to existing NoteHelper customer
        customer_id = customer_lookup.get(customer_name.lower())
        
        # Get seller from territory alignments if provided
        seller_name = None
        if territory_alignments:
            seller_name = territory_alignments.get((customer_name, bucket))
        
        # Process each month column
        for month_col, month_date in month_dates.items():
            revenue = parse_currency(row.get(month_col, 0))
            fiscal_month = month_col
            
            # Determine if this is a bucket total or product detail
            is_bucket_total = (product.lower() == 'total' or product == '')
            
            if is_bucket_total:
                # Store in CustomerRevenueData (for analysis)
                existing = CustomerRevenueData.query.filter_by(
                    customer_name=customer_name,
                    bucket=bucket,
                    month_date=month_date
                ).first()
                
                if existing:
                    if existing.revenue != revenue:
                        existing.revenue = revenue
                        existing.last_updated_at = datetime.utcnow()
                        existing.last_import_id = import_record.id
                        bucket_records_updated += 1
                    if customer_id and not existing.customer_id:
                        existing.customer_id = customer_id
                    if seller_name and not existing.seller_name:
                        existing.seller_name = seller_name
                else:
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
                    bucket_records_created += 1
                    
                    # Track new months
                    existing_months = db.session.query(
                        CustomerRevenueData.month_date
                    ).filter(
                        CustomerRevenueData.month_date == month_date
                    ).first()
                    if not existing_months:
                        new_months.add(month_date)
            else:
                # Store in ProductRevenueData (for drill-down)
                existing = ProductRevenueData.query.filter_by(
                    customer_name=customer_name,
                    bucket=bucket,
                    product=product,
                    month_date=month_date
                ).first()
                
                if existing:
                    if existing.revenue != revenue:
                        existing.revenue = revenue
                        existing.last_updated_at = datetime.utcnow()
                        existing.last_import_id = import_record.id
                        product_records_updated += 1
                    if customer_id and not existing.customer_id:
                        existing.customer_id = customer_id
                else:
                    new_record = ProductRevenueData(
                        customer_name=customer_name,
                        bucket=bucket,
                        product=product,
                        customer_id=customer_id,
                        fiscal_month=fiscal_month,
                        month_date=month_date,
                        revenue=revenue,
                        last_import_id=import_record.id
                    )
                    db.session.add(new_record)
                    product_records_created += 1
    
    # Update import stats
    import_record.records_created = bucket_records_created + product_records_created
    import_record.records_updated = bucket_records_updated + product_records_updated
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


def get_product_revenue_history(
    customer_name: str,
    bucket: str,
    product: Optional[str] = None
) -> list[ProductRevenueData]:
    """Get product-level revenue history for a customer/bucket.
    
    Args:
        customer_name: Customer name to look up
        bucket: Bucket name (Core DBs, Analytics, Modern DBs)
        product: Optional specific product filter
        
    Returns:
        List of ProductRevenueData records ordered by product then month
    """
    query = ProductRevenueData.query.filter_by(
        customer_name=customer_name,
        bucket=bucket
    )
    
    if product:
        query = query.filter_by(product=product)
    
    return query.order_by(
        ProductRevenueData.product,
        ProductRevenueData.month_date
    ).all()


def get_products_for_bucket(customer_name: str, bucket: str) -> list[dict]:
    """Get all products used by a customer in a specific bucket with totals.
    
    Args:
        customer_name: Customer name
        bucket: Bucket name
        
    Returns:
        List of dicts with product name and total revenue
    """
    results = db.session.query(
        ProductRevenueData.product,
        db.func.sum(ProductRevenueData.revenue).label('total_revenue'),
        db.func.count(ProductRevenueData.id).label('month_count')
    ).filter_by(
        customer_name=customer_name,
        bucket=bucket
    ).group_by(
        ProductRevenueData.product
    ).order_by(
        db.func.sum(ProductRevenueData.revenue).desc()
    ).all()
    
    return [
        {
            'product': r.product,
            'total_revenue': r.total_revenue or 0,
            'month_count': r.month_count
        }
        for r in results
    ]


def get_all_products() -> list[dict]:
    """Get all unique products in the database with usage stats.
    
    Returns:
        List of dicts with product name, customer count, total revenue
    """
    results = db.session.query(
        ProductRevenueData.product,
        db.func.count(db.distinct(ProductRevenueData.customer_name)).label('customer_count'),
        db.func.sum(ProductRevenueData.revenue).label('total_revenue')
    ).group_by(
        ProductRevenueData.product
    ).order_by(
        db.func.sum(ProductRevenueData.revenue).desc()
    ).all()
    
    return [
        {
            'product': r.product,
            'customer_count': r.customer_count,
            'total_revenue': r.total_revenue or 0
        }
        for r in results
    ]


def get_customers_using_product(product: str) -> list[dict]:
    """Get all customers using a specific product with their revenue history.
    
    Args:
        product: Product name to look up
        
    Returns:
        List of dicts with customer info and revenue data
    """
    # Get latest revenue for each customer using this product
    results = db.session.query(
        ProductRevenueData.customer_name,
        ProductRevenueData.bucket,
        ProductRevenueData.customer_id,
        db.func.sum(ProductRevenueData.revenue).label('total_revenue'),
        db.func.max(ProductRevenueData.month_date).label('latest_month')
    ).filter_by(
        product=product
    ).group_by(
        ProductRevenueData.customer_name,
        ProductRevenueData.bucket,
        ProductRevenueData.customer_id
    ).order_by(
        db.func.sum(ProductRevenueData.revenue).desc()
    ).all()
    
    return [
        {
            'customer_name': r.customer_name,
            'bucket': r.bucket,
            'customer_id': r.customer_id,
            'total_revenue': r.total_revenue or 0,
            'latest_month': r.latest_month
        }
        for r in results
    ]


def get_seller_products(seller_name: str) -> list[dict]:
    """Get all unique products used by a seller's customers.
    
    Args:
        seller_name: Seller name to filter by
        
    Returns:
        List of dicts with product name, customer count, total revenue
    """
    # Get customer names for this seller from analyses
    from app.models import RevenueAnalysis
    seller_customers = db.session.query(
        db.distinct(RevenueAnalysis.customer_name)
    ).filter_by(seller_name=seller_name).subquery()
    
    results = db.session.query(
        ProductRevenueData.product,
        db.func.count(db.distinct(ProductRevenueData.customer_name)).label('customer_count'),
        db.func.sum(ProductRevenueData.revenue).label('total_revenue')
    ).filter(
        ProductRevenueData.customer_name.in_(seller_customers)
    ).group_by(
        ProductRevenueData.product
    ).order_by(
        db.func.sum(ProductRevenueData.revenue).desc()
    ).all()
    
    return [
        {
            'product': r.product,
            'customer_count': r.customer_count,
            'total_revenue': r.total_revenue or 0
        }
        for r in results
    ]


def get_seller_customers_using_product(seller_name: str, product: str) -> list[dict]:
    """Get seller's customers using a specific product.
    
    Args:
        seller_name: Seller name to filter by
        product: Product name to look up
        
    Returns:
        List of dicts with customer info and revenue data
    """
    # Get customer names for this seller from analyses
    from app.models import RevenueAnalysis
    seller_customers = db.session.query(
        db.distinct(RevenueAnalysis.customer_name)
    ).filter_by(seller_name=seller_name).subquery()
    
    results = db.session.query(
        ProductRevenueData.customer_name,
        ProductRevenueData.bucket,
        ProductRevenueData.customer_id,
        db.func.sum(ProductRevenueData.revenue).label('total_revenue'),
        db.func.max(ProductRevenueData.month_date).label('latest_month')
    ).filter(
        ProductRevenueData.product == product,
        ProductRevenueData.customer_name.in_(seller_customers)
    ).group_by(
        ProductRevenueData.customer_name,
        ProductRevenueData.bucket,
        ProductRevenueData.customer_id
    ).order_by(
        db.func.sum(ProductRevenueData.revenue).desc()
    ).all()
    
    return [
        {
            'customer_name': r.customer_name,
            'bucket': r.bucket,
            'customer_id': r.customer_id,
            'total_revenue': r.total_revenue or 0,
            'latest_month': r.latest_month
        }
        for r in results
    ]