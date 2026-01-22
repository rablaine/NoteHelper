"""
Services module for NoteHelper.
Contains business logic services separate from routes.
"""

from app.services.revenue_import import (
    import_revenue_csv,
    parse_currency,
    fiscal_month_to_date,
    date_to_fiscal_month,
    get_import_history,
    get_months_in_database,
    get_customer_revenue_history,
    RevenueImportError
)

from app.services.revenue_analysis import (
    AnalysisConfig,
    CustomerSignals,
    compute_signals,
    categorize_customer,
    determine_action,
    run_analysis_for_all,
    get_actionable_analyses,
    get_seller_alerts
)

__all__ = [
    # Import functions
    'import_revenue_csv',
    'parse_currency',
    'fiscal_month_to_date',
    'date_to_fiscal_month',
    'get_import_history',
    'get_months_in_database',
    'get_customer_revenue_history',
    'RevenueImportError',
    # Analysis functions
    'AnalysisConfig',
    'CustomerSignals',
    'compute_signals',
    'categorize_customer',
    'determine_action',
    'run_analysis_for_all',
    'get_actionable_analyses',
    'get_seller_alerts'
]
