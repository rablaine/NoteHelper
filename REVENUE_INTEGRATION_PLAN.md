# Revenue Analyzer Integration Plan

## Overview

Integrate the revenue-analyzer tool into NoteHelper to provide revenue health insights for customers and surface actionable recommendations to sellers.

**Current State:**
- `revenue-analyzer` is a standalone Python tool with a Tkinter GUI
- Takes a CSV export from MSXI (ACR Details by Quarter/Month report)
- Analyzes revenue trends across product buckets (Core DBs, Analytics, Modern DBs)
- Outputs recommendations with priority scores, $ at risk, $ opportunity

**Goal:**
- Integrate analysis into NoteHelper web app
- Surface recommendations on customer pages and a dedicated "Attention Needed" dashboard
- Track changes between imports to highlight new/resolved issues
- Allow sellers to create call logs directly from recommendations

---

## Feature Requirements

### 1. Revenue Data Import
- Upload CSV from MSXI (same format as standalone tool)
- Store raw revenue data and computed analysis in database
- Track import history (when, who, file stats)
- Support re-imports to update recommendations

### 2. Analysis Engine
- Port analysis logic from `revenue_analyzer.py` to NoteHelper
- Apply configurable thresholds (can use defaults from standalone tool)
- Compute all signals: trend slope, volatility, $ at risk, $ opportunity
- Assign categories and recommended actions

### 3. Customer Integration
- Match analyzed customers to existing NoteHelper customers by name and/or TPID
- Show revenue health card on customer detail page
- Display: current status, trend, $ at risk/opportunity, recommendation
- Surface monthly revenue history

### 4. Actionable Dashboard
- New page: "Customers Needing Attention" or "Revenue Alerts"
- Filter by: category, recommended action, seller, territory
- Sort by: priority score, $ at risk, $ opportunity
- Click-through to customer page or create call log directly

### 5. Change Tracking
- Compare current import to previous import
- Highlight: new alerts, resolved alerts, status changes
- Show "What's changed since last week" summary

---

## Data Model Design

### Key Insight: Accumulate Historical Data

Unlike the standalone script (which only sees 6-7 months from one CSV), our database can **accumulate revenue data over time**. Each import adds new months and updates in-progress values, building a richer dataset for analysis.

**Benefits:**
- See revenue trends on customer pages immediately (no analysis needed)
- Run analysis with 12+ months of data instead of 6-7
- Better trend detection with more data points
- Track how revenue evolved over fiscal year

**Handling Partial Months:**
- The most recent month in CSV is always "in-progress" (not final)
- Just upsert it - next import will update the value
- Analysis excludes the most recent month dynamically (same as script does today)
- No need to track "is_final" flag - simpler data model

### New Tables

```python
class RevenueImport(db.Model):
    """Tracks each revenue data import."""
    __tablename__ = 'revenue_imports'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    imported_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Stats about this import
    record_count = db.Column(db.Integer, nullable=False)  # Customer/bucket rows in CSV
    new_months_added = db.Column(db.Integer, default=0)  # New month columns we hadn't seen
    records_updated = db.Column(db.Integer, default=0)  # Existing records updated
    records_created = db.Column(db.Integer, default=0)  # New records created
    
    # Month range in this import
    earliest_month = db.Column(db.Date, nullable=True)
    latest_month = db.Column(db.Date, nullable=True)
    
    # Relationships
    data_points = db.relationship('CustomerRevenueData', back_populates='last_import', lazy='select')


class CustomerRevenueData(db.Model):
    """Monthly revenue data point for a customer/bucket combination.
    
    This is the RAW DATA layer - stores every customer's monthly revenue
    whether they're flagged for engagement or not. Accumulates over imports.
    """
    __tablename__ = 'customer_revenue_data'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Customer identification (from CSV)
    customer_name = db.Column(db.String(500), nullable=False, index=True)
    tpid = db.Column(db.String(50), nullable=True, index=True)
    seller_name = db.Column(db.String(200), nullable=True)  # From territory alignment in CSV
    bucket = db.Column(db.String(50), nullable=False)  # Core DBs, Analytics, Modern DBs
    
    # Link to NoteHelper customer (nullable until matched)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    
    # Month identifier
    fiscal_month = db.Column(db.String(20), nullable=False)  # e.g., "FY26-Jan" for display
    month_date = db.Column(db.Date, nullable=False, index=True)  # First of month, for sorting
    
    # Revenue value
    revenue = db.Column(db.Float, nullable=False, default=0.0)
    
    # Tracking
    first_imported_at = db.Column(db.DateTime, nullable=False)
    last_updated_at = db.Column(db.DateTime, nullable=False)
    last_import_id = db.Column(db.Integer, db.ForeignKey('revenue_imports.id'), nullable=False)
    
    # Relationships
    last_import = db.relationship('RevenueImport', back_populates='data_points')
    customer = db.relationship('Customer', backref='revenue_data_points')
    
    # Unique constraint: one record per customer/bucket/month
    __table_args__ = (
        db.UniqueConstraint('customer_name', 'bucket', 'month_date', name='uq_customer_bucket_month'),
        db.Index('ix_revenue_data_lookup', 'customer_name', 'bucket'),  # For fast lookups
    )


class RevenueAnalysis(db.Model):
    """Computed analysis for a customer/bucket - regenerated on demand or after import.
    
    This is the ANALYSIS layer - computed from CustomerRevenueData.
    Can be regenerated anytime from the raw data.
    """
    __tablename__ = 'revenue_analyses'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to customer (by name for unmatched, by ID when matched)
    customer_name = db.Column(db.String(500), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    tpid = db.Column(db.String(50), nullable=True)
    seller_name = db.Column(db.String(200), nullable=True)
    bucket = db.Column(db.String(50), nullable=False)
    
    # When was this analysis computed?
    analyzed_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    months_analyzed = db.Column(db.Integer, nullable=False)  # How many months of data used
    
    # Revenue summary
    avg_revenue = db.Column(db.Float, nullable=False)
    latest_revenue = db.Column(db.Float, nullable=False)  # Most recent final month
    
    # Analysis results
    category = db.Column(db.String(50), nullable=False)  # CHURN_RISK, RECENT_DIP, etc.
    recommended_action = db.Column(db.String(50), nullable=False)  # CHECK-IN (Urgent), etc.
    confidence = db.Column(db.String(20), nullable=False)  # LOW, MEDIUM, HIGH
    priority_score = db.Column(db.Integer, nullable=False)  # 0-100
    
    # Dollar impact
    dollars_at_risk = db.Column(db.Float, default=0.0)
    dollars_opportunity = db.Column(db.Float, default=0.0)
    
    # Statistical signals
    trend_slope = db.Column(db.Float, default=0.0)  # %/month
    last_month_change = db.Column(db.Float, default=0.0)
    last_2month_change = db.Column(db.Float, default=0.0)
    volatility_cv = db.Column(db.Float, default=0.0)
    max_drawdown = db.Column(db.Float, default=0.0)
    current_vs_max = db.Column(db.Float, default=0.0)
    current_vs_avg = db.Column(db.Float, default=0.0)
    
    # Engagement rationale (plain English)
    engagement_rationale = db.Column(db.Text, nullable=True)
    
    # For change tracking - previous analysis values
    previous_category = db.Column(db.String(50), nullable=True)
    previous_priority_score = db.Column(db.Integer, nullable=True)
    status_changed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    customer = db.relationship('Customer', backref='revenue_analyses')
    
    # Unique constraint: one active analysis per customer/bucket
    __table_args__ = (
        db.UniqueConstraint('customer_name', 'bucket', name='uq_analysis_customer_bucket'),
    )


class RevenueConfig(db.Model):
    """User-configurable thresholds for revenue analysis."""
    __tablename__ = 'revenue_config'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Revenue gates
    min_revenue_for_outreach = db.Column(db.Integer, default=3000)
    min_dollar_impact = db.Column(db.Integer, default=1000)
    dollar_at_risk_override = db.Column(db.Integer, default=2000)
    dollar_opportunity_override = db.Column(db.Integer, default=1500)
    
    # Revenue tiers
    high_value_threshold = db.Column(db.Integer, default=25000)
    strategic_threshold = db.Column(db.Integer, default=50000)
    
    # Category thresholds
    volatile_min_revenue = db.Column(db.Integer, default=5000)
    recent_drop_threshold = db.Column(db.Float, default=-0.15)  # -15%
    expansion_growth_threshold = db.Column(db.Float, default=0.08)  # 8%
```

---

## Import Logic Flow

### What Happens on Each Import

```
1. Parse CSV
   ├── Extract month columns (e.g., FY26-Jul through FY26-Jan)
   ├── Identify which month is "current" (in-progress)
   └── Parse all customer/bucket rows

2. For each customer/bucket row:
   ├── For each month column:
   │   ├── Look for existing CustomerRevenueData record
   │   ├── If exists: update revenue value + last_updated_at
   │   └── If not exists: create new record
   └── Track stats (created, updated counts)

3. After all data loaded:
   ├── Run analysis on all customer/buckets with data
   ├── Update RevenueAnalysis records
   ├── Compare to previous analysis for change detection
   └── Store import stats
```

### Example: Building History Over Time

**First import (January):**
- CSV has: Jul, Aug, Sep, Oct, Nov, Dec, Jan(partial)
- Store 6 final months + 1 in-progress
- Analysis uses 6 months

**Second import (February):**
- CSV has: Aug, Sep, Oct, Nov, Dec, Jan, Feb(partial)
- Jan gets marked final (Feb is now current)
- Jul data retained from previous import!
- Analysis now uses 7 months

**After 6 months of imports:**
- We have 12+ months of data
- Much better trend analysis
- Can detect seasonal patterns

### Customer Model Changes

Add methods to access revenue data and analysis:

```python
# In Customer model
def get_revenue_history(self, bucket=None):
    """Get all revenue data points for this customer, optionally filtered by bucket.
    
    Returns list of CustomerRevenueData ordered by month.
    """
    query = CustomerRevenueData.query.filter_by(customer_id=self.id)
    if bucket:
        query = query.filter_by(bucket=bucket)
    return query.order_by(CustomerRevenueData.month_date.asc()).all()

def get_revenue_by_bucket(self):
    """Get revenue history grouped by bucket.
    
    Returns dict: {bucket_name: [data_points]}
    """
    from collections import defaultdict
    history = defaultdict(list)
    for dp in self.get_revenue_history():
        history[dp.bucket].append(dp)
    return dict(history)

def get_latest_analysis(self, bucket=None):
    """Get most recent analysis for this customer, optionally filtered by bucket."""
    query = RevenueAnalysis.query.filter_by(customer_id=self.id)
    if bucket:
        query = query.filter_by(bucket=bucket)
    return query.order_by(RevenueAnalysis.priority_score.desc()).first()

def get_all_analyses(self):
    """Get all analyses for this customer (one per bucket)."""
    return RevenueAnalysis.query.filter_by(customer_id=self.id)\
        .order_by(RevenueAnalysis.priority_score.desc()).all()

def get_revenue_status_summary(self):
    """Get summary of revenue health across all buckets.
    
    Returns the most urgent status if multiple buckets exist.
    """
    analyses = self.get_all_analyses()
    if not analyses:
        return None
    
    # Return worst status (highest priority)
    worst = analyses[0]
    return {
        'bucket': worst.bucket,
        'category': worst.category,
        'action': worst.recommended_action,
        'priority': worst.priority_score,
        'at_risk': worst.dollars_at_risk,
        'opportunity': worst.dollars_opportunity,
        'rationale': worst.engagement_rationale,
        'total_buckets': len(analyses),
        'all_analyses': analyses
    }

def has_revenue_data(self):
    """Check if this customer has any revenue data."""
    return CustomerRevenueData.query.filter_by(customer_id=self.id).first() is not None
```

---

## UI/UX Design

### 1. Import Flow

**Location:** Admin panel or new "Revenue Data" section in nav

**Steps:**
1. Click "Import Revenue Data"
2. File picker for CSV
3. Preview: shows record count, date range, product buckets found
4. Optional: Configure thresholds (collapsible, defaults pre-filled)
5. Click "Run Analysis"
6. Progress indicator during processing
7. Summary: X customers analyzed, Y needing attention, Z matched to existing customers

### 2. Customer Page Enhancement

Add "Revenue Health" card to customer detail view:

```
┌─────────────────────────────────────────────────────┐
│ 📊 Revenue Health                      [Core DBs]   │
├─────────────────────────────────────────────────────┤
│ Status: 🚨 CHURN RISK                               │
│ Priority: 85/100                                    │
│                                                     │
│ Avg Monthly: $9,096                                 │
│ Trend: -12.3%/month declining                       │
│ $ At Risk: $1,115/month                             │
│                                                     │
│ "High volatility, declining 12%/month, down 15%    │
│  over 2 months, at 57% of historical peak."        │
│                                                     │
│ [View History] [Create Call Log]                    │
└─────────────────────────────────────────────────────┘
```

### 3. Attention Dashboard

New page accessible from nav: "Revenue Alerts" or "Customers Needing Attention"

**Features:**
- Table of customers with actionable recommendations
- Columns: Customer, Seller, Category, Action, Priority, $ At Risk, $ Opportunity, Rationale
- Filters: Category dropdown, Action dropdown, Seller dropdown, Territory dropdown
- Sort: Click column headers
- Row actions: View Customer, Create Call Log
- Badge in nav showing count of urgent items

### 4. What's Changed View

After re-import, show diff summary:

- **New Alerts:** Customers that weren't flagged before, now are
- **Resolved:** Customers that were flagged, now healthy
- **Worsened:** Customers whose category or priority got worse
- **Improved:** Customers whose category or priority got better

---

## Implementation Phases

### Phase 1: Data Layer (Foundation)
- [ ] Database models + migration (RevenueImport, CustomerRevenueData, RevenueAnalysis, RevenueConfig)
- [ ] CSV parsing logic (extract months, customer rows, revenue values)
- [ ] Import service: upsert CustomerRevenueData records
- [ ] Basic import route (API endpoint, no fancy UI yet)
- [ ] Tests for import logic

### Phase 2: Analysis Engine
- [ ] Port analysis logic from `revenue_analyzer.py`
- [ ] Adapt to use accumulated historical data (not just CSV months)
- [ ] Generate RevenueAnalysis records from CustomerRevenueData
- [ ] Change detection: compare new vs previous analysis
- [ ] Configurable thresholds (use defaults from standalone tool)

### Phase 3: Customer Integration  
- [ ] Match imported customers to NoteHelper customers (by name, TPID)
- [ ] Add revenue history card to customer detail page
- [ ] Show mini revenue chart (sparkline) on customer list?
- [ ] Handle unmatched customers (list them, allow manual linking)

### Phase 4: Dashboard
- [ ] "Attention Needed" dashboard page
- [ ] Filtering: category, action, seller, territory, bucket
- [ ] Sorting: priority, $ at risk, $ opportunity
- [ ] Click-through to customer or create call log

### Phase 5: Change Tracking & History
- [ ] "What's Changed" summary after import
- [ ] Show status changes on dashboard (new alerts, resolved, worsened)
- [ ] Revenue trend visualization over time

### Phase 6: Polish & UX
- [ ] Nice import UI with file picker and preview
- [ ] Configuration UI for thresholds
- [ ] Export current recommendations to CSV
- [ ] Import history log

---

## Open Questions (To Discuss with Team)

1. **Customer Matching:**
   - Match by name only? Name + TPID? Fuzzy matching?
   - What about customers in CSV not yet in NoteHelper?
   - Auto-create customers from import? Or just flag unmatched?
   - UI for manually linking unmatched customers?

2. **Multi-bucket Handling:**
   - Customer can appear in multiple buckets (Core DBs, Analytics, Modern DBs)
   - Show all buckets on customer page? (probably yes)
   - Which bucket to highlight in "worst status" summary?
   - Aggregate dollar amounts across buckets?

3. **Historical Data Retention:**
   - Keep revenue data forever? (probably yes, it's useful)
   - Prune RevenueImport records after X months? (keep data, prune import logs?)
   - How far back can we realistically go? (limited by MSXI report availability)

4. **Analysis Timing:**
   - Re-run analysis automatically after every import?
   - Allow manual "re-analyze" button?
   - Re-analyze when thresholds change?

5. **Seller Assignment from CSV:**
   - CSV has seller name from territory alignment
   - Match to NoteHelper sellers? Or just display as text?
   - What if CSV seller differs from NoteHelper customer's seller?

6. **Analysis Algorithm:**
   - Use current revenue-analyzer logic as-is for MVP?
   - Adapt for longer history (12+ months)?
   - Weight recent months more heavily?
   - Seasonal adjustment (compare to same month last year)?

7. **Fiscal Month Parsing:**
   - CSV uses "FY26-Jan" format
   - Convert to actual dates for storage (2026-01-01)?
   - Handle fiscal year boundaries (FY26 = Jul 2025 - Jun 2026)?

---

## Technical Notes

### Code to Port from `revenue_analyzer.py`

Key functions to adapt:
- `compute_signals()` - Calculate statistical signals
- `categorize_customer()` - Assign engagement category
- `determine_action()` - Map to recommended action
- `compute_priority_score()` - Calculate sorting priority
- `generate_rationale()` - Plain English explanation

These can become methods on `RevenueSnapshot` or a service class.

### Dependencies

Current `revenue_analyzer.py` uses:
- `pandas` (for CSV parsing)
- Standard library: `statistics`, `datetime`, `dataclasses`

NoteHelper already has SQLAlchemy, so we can either:
- Add pandas to requirements (it's lightweight for just CSV parsing)
- Use Python's `csv` module instead

### File Size Considerations

Sample CSV is ~50KB with ~100 rows. Should scale fine.
For very large files (thousands of customers), consider:
- Chunked processing
- Background task with progress updates
- Database batch inserts

---

## References

- [REVENUE_ANALYZER.md](../DSEWorkTools/revenue-analyzer/REVENUE_ANALYZER.md) - Original tool documentation
- [HOW_WE_ANALYZE.md](../DSEWorkTools/revenue-analyzer/HOW_WE_ANALYZE.md) - Analysis methodology
- [revenue_analyzer.py](../DSEWorkTools/revenue-analyzer/revenue_analyzer.py) - Core analysis logic

---

**Last Updated:** $(Get-Date -Format "MMMM dd, yyyy")
**Status:** Planning / Brainstorming

