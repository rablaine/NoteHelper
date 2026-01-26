"""
Revenue routes for NoteHelper.
Handles revenue data import, analysis, and attention dashboard.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g, Response
from werkzeug.utils import secure_filename
import csv
from io import StringIO

from app.models import (
    db, RevenueImport, CustomerRevenueData, ProductRevenueData, RevenueAnalysis, 
    RevenueConfig, RevenueEngagement, Customer, Seller
)
from app.services.revenue_import import (
    import_revenue_csv, get_import_history, get_months_in_database,
    get_customer_revenue_history, get_product_revenue_history,
    get_products_for_bucket, get_all_products, get_customers_using_product,
    RevenueImportError
)
from app.services.revenue_analysis import (
    run_analysis_for_all, get_actionable_analyses, get_seller_alerts,
    AnalysisConfig
)

# Create blueprint
revenue_bp = Blueprint('revenue', __name__)


@revenue_bp.route('/revenue')
def revenue_dashboard():
    """Main revenue attention dashboard."""
    # Get actionable analyses
    analyses = get_actionable_analyses(min_priority=20, limit=50)
    
    # Group by category for summary
    category_counts = {}
    for a in analyses:
        cat = a.category
        if cat not in category_counts:
            category_counts[cat] = {'count': 0, 'total_at_risk': 0, 'total_opportunity': 0}
        category_counts[cat]['count'] += 1
        category_counts[cat]['total_at_risk'] += a.dollars_at_risk or 0
        category_counts[cat]['total_opportunity'] += a.dollars_opportunity or 0
    
    # Get unique sellers with alerts
    seller_names = db.session.query(RevenueAnalysis.seller_name).filter(
        RevenueAnalysis.seller_name.isnot(None),
        RevenueAnalysis.recommended_action.notin_(["NO ACTION", "MONITOR"])
    ).distinct().all()
    sellers_with_alerts = [s[0] for s in seller_names if s[0]]
    
    # Get import stats
    latest_import = RevenueImport.query.order_by(RevenueImport.imported_at.desc()).first()
    months_data = get_months_in_database()
    
    return render_template(
        'revenue_dashboard.html',
        analyses=analyses,
        category_counts=category_counts,
        sellers_with_alerts=sellers_with_alerts,
        latest_import=latest_import,
        months_data=months_data
    )


@revenue_bp.route('/revenue/import', methods=['GET', 'POST'])
def revenue_import():
    """Import revenue CSV data."""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if not file.filename.endswith('.csv'):
            flash('Only CSV files are supported', 'error')
            return redirect(request.url)
        
        try:
            filename = secure_filename(file.filename)
            content = file.read()
            
            # Import the data
            import_record = import_revenue_csv(
                file_content=content,
                filename=filename,
                user_id=g.user.id
            )
            
            # Run analysis after import
            run_analysis = request.form.get('run_analysis', 'on') == 'on'
            if run_analysis:
                analysis_stats = run_analysis_for_all(user_id=g.user.id)
                flash(
                    f'Imported {import_record.records_created} new records, '
                    f'updated {import_record.records_updated}. '
                    f'Analyzed {analysis_stats["analyzed"]} customers, '
                    f'{analysis_stats["actionable"]} need attention.',
                    'success'
                )
            else:
                flash(
                    f'Imported {import_record.records_created} new records, '
                    f'updated {import_record.records_updated}.',
                    'success'
                )
            
            return redirect(url_for('revenue.revenue_dashboard'))
            
        except RevenueImportError as e:
            flash(f'Import error: {str(e)}', 'error')
            return redirect(request.url)
        except Exception as e:
            flash(f'Unexpected error: {str(e)}', 'error')
            return redirect(request.url)
    
    # GET - show import form
    import_history = get_import_history(limit=10)
    months_data = get_months_in_database()
    
    return render_template(
        'revenue_import.html',
        import_history=import_history,
        months_data=months_data
    )


@revenue_bp.route('/revenue/analyze', methods=['POST'])
def revenue_analyze():
    """Re-run analysis on all revenue data."""
    try:
        stats = run_analysis_for_all(user_id=g.user.id)
        flash(
            f'Analysis complete: {stats["analyzed"]} customers analyzed, '
            f'{stats["actionable"]} need attention, '
            f'{stats["skipped"]} skipped (insufficient data).',
            'success'
        )
    except Exception as e:
        flash(f'Analysis error: {str(e)}', 'error')
    
    return redirect(url_for('revenue.revenue_dashboard'))


@revenue_bp.route('/revenue/seller/<seller_name>')
def revenue_seller_view(seller_name: str):
    """View revenue alerts for a specific seller."""
    # Get alerts for this seller
    alerts = get_seller_alerts(seller_name)
    
    # Calculate totals
    total_at_risk = sum(a.dollars_at_risk or 0 for a in alerts)
    total_opportunity = sum(a.dollars_opportunity or 0 for a in alerts)
    
    # Try to match to a NoteHelper Seller
    seller = Seller.query.filter(
        db.func.lower(Seller.name) == seller_name.lower()
    ).first()
    
    return render_template(
        'revenue_seller_alerts.html',
        seller_name=seller_name,
        seller=seller,
        alerts=alerts,
        total_at_risk=total_at_risk,
        total_opportunity=total_opportunity
    )


@revenue_bp.route('/revenue/seller/<seller_name>/export')
def revenue_seller_export(seller_name: str):
    """Export seller's alerts as CSV for sending via Teams."""
    alerts = get_seller_alerts(seller_name)
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Customer', 'TPID', 'Bucket', 'Avg Revenue', 'Category',
        'Recommended Action', 'Rationale', '$ At Risk/Month', '$ Opportunity/Month',
        'Priority Score', 'Confidence', 'Trend %/Month'
    ])
    
    # Data rows
    for a in alerts:
        writer.writerow([
            a.customer_name,
            a.tpid or '',
            a.bucket,
            f'${a.avg_revenue:,.0f}',
            a.category,
            a.recommended_action,
            a.engagement_rationale,
            f'${a.dollars_at_risk:,.0f}' if a.dollars_at_risk else '',
            f'${a.dollars_opportunity:,.0f}' if a.dollars_opportunity else '',
            a.priority_score,
            a.confidence,
            f'{a.trend_slope:+.1f}%'
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={seller_name}_revenue_alerts.csv'
        }
    )


@revenue_bp.route('/revenue/customer/<customer_name>')
def revenue_customer_view(customer_name: str):
    """View revenue history and analysis for a specific customer."""
    # Get all analyses for this customer (all buckets)
    analyses = RevenueAnalysis.query.filter_by(customer_name=customer_name).all()
    
    # Get revenue history by bucket
    buckets = ['Core DBs', 'Analytics', 'Modern DBs']
    revenue_by_bucket = {}
    products_by_bucket = {}
    bucket_product_data = {}  # Full product data with monthly revenues
    
    for bucket in buckets:
        history = get_customer_revenue_history(customer_name, bucket)
        if history:
            revenue_by_bucket[bucket] = history
            # Get products for this bucket
            products = get_products_for_bucket(customer_name, bucket)
            products_by_bucket[bucket] = products
            
            # Get product history for grid display
            product_history = {}
            for p in products:
                p_history = get_product_revenue_history(customer_name, bucket, p['product'])
                if p_history:
                    product_history[p['product']] = p_history
            
            # Get the 7 most recent months for this bucket
            all_months = {}
            for ph in product_history.values():
                for rd in ph:
                    all_months[rd.fiscal_month] = rd.month_date
            # Also include bucket totals months
            for rd in history:
                all_months[rd.fiscal_month] = rd.month_date
            sorted_months = sorted(all_months.items(), key=lambda x: x[1])
            recent_months = [m[0] for m in sorted_months[-7:]]
            
            # Build product summary with monthly revenues
            product_summary = []
            for p in products:
                p_hist = product_history.get(p['product'], [])
                month_revenues = {rd.fiscal_month: rd.revenue for rd in p_hist}
                product_summary.append({
                    'product': p['product'],
                    'total_revenue': p['total_revenue'],
                    'month_revenues': month_revenues
                })
            
            # Build bucket total monthly revenues
            bucket_month_revenues = {rd.fiscal_month: rd.revenue for rd in history}
            
            bucket_product_data[bucket] = {
                'recent_months': recent_months,
                'product_summary': product_summary,
                'bucket_month_revenues': bucket_month_revenues,
                'bucket_total': sum(rd.revenue for rd in history)
            }
    
    # Try to match to a NoteHelper Customer
    customer = Customer.query.filter(
        db.func.lower(Customer.name) == customer_name.lower()
    ).first()
    
    return render_template(
        'revenue_customer_view.html',
        customer_name=customer_name,
        customer=customer,
        analyses=analyses,
        revenue_by_bucket=revenue_by_bucket,
        products_by_bucket=products_by_bucket,
        bucket_product_data=bucket_product_data
    )


@revenue_bp.route('/revenue/customer/<customer_name>/bucket/<bucket>')
def revenue_bucket_products(customer_name: str, bucket: str):
    """View product-level revenue breakdown for a customer/bucket."""
    # Get products with totals
    products = get_products_for_bucket(customer_name, bucket)
    
    # Get product history for drill-down
    product_history = {}
    for p in products:
        history = get_product_revenue_history(customer_name, bucket, p['product'])
        if history:
            product_history[p['product']] = history
    
    # Get the 7 most recent months across all products for the summary table
    # Use (month_date, fiscal_month) tuples to sort chronologically
    all_months = {}
    for history in product_history.values():
        for rd in history:
            all_months[rd.fiscal_month] = rd.month_date
    # Sort by actual date, then take most recent 7
    sorted_months = sorted(all_months.items(), key=lambda x: x[1])
    recent_months = [m[0] for m in sorted_months[-7:]]
    
    # Build summary data for each product: monthly revenue for recent months
    product_summary = []
    for p in products:
        history = product_history.get(p['product'], [])
        month_revenues = {rd.fiscal_month: rd.revenue for rd in history}
        product_summary.append({
            'product': p['product'],
            'total_revenue': p['total_revenue'],
            'month_revenues': month_revenues
        })
    
    # Get the bucket-level analysis if it exists
    analysis = RevenueAnalysis.query.filter_by(
        customer_name=customer_name,
        bucket=bucket
    ).first()
    
    # Try to match to NoteHelper customer
    customer = Customer.query.filter(
        db.func.lower(Customer.name) == customer_name.lower()
    ).first()
    
    return render_template(
        'revenue_bucket_products.html',
        customer_name=customer_name,
        customer=customer,
        bucket=bucket,
        products=products,
        product_history=product_history,
        product_summary=product_summary,
        recent_months=recent_months,
        analysis=analysis
    )


@revenue_bp.route('/revenue/products')
def revenue_products_list():
    """List all products with usage statistics."""
    products = get_all_products()
    return render_template('revenue_products_list.html', products=products)


@revenue_bp.route('/revenue/product/<product>')
def revenue_product_view(product: str):
    """View all customers using a specific product."""
    customers = get_customers_using_product(product)
    
    # Get historical revenue for each customer
    customer_history = {}
    for c in customers:
        history = ProductRevenueData.query.filter_by(
            customer_name=c['customer_name'],
            bucket=c['bucket'],
            product=product
        ).order_by(ProductRevenueData.month_date).all()
        if history:
            customer_history[c['customer_name']] = history
    
    return render_template(
        'revenue_product_view.html',
        product=product,
        customers=customers,
        customer_history=customer_history
    )


@revenue_bp.route('/revenue/config', methods=['GET', 'POST'])
def revenue_config():
    """Configure revenue analysis thresholds."""
    config = RevenueConfig.query.filter_by(user_id=g.user.id).first()
    
    if request.method == 'POST':
        if not config:
            config = RevenueConfig(user_id=g.user.id)
            db.session.add(config)
        
        # Update values from form
        config.min_revenue_for_outreach = int(request.form.get('min_revenue_for_outreach', 3000))
        config.min_dollar_impact = int(request.form.get('min_dollar_impact', 1000))
        config.dollar_at_risk_override = int(request.form.get('dollar_at_risk_override', 2000))
        config.dollar_opportunity_override = int(request.form.get('dollar_opportunity_override', 1500))
        config.high_value_threshold = int(request.form.get('high_value_threshold', 25000))
        config.strategic_threshold = int(request.form.get('strategic_threshold', 50000))
        config.volatile_min_revenue = int(request.form.get('volatile_min_revenue', 5000))
        config.recent_drop_threshold = float(request.form.get('recent_drop_threshold', -0.15))
        config.expansion_growth_threshold = float(request.form.get('expansion_growth_threshold', 0.08))
        
        db.session.commit()
        flash('Configuration saved', 'success')
        return redirect(url_for('revenue.revenue_dashboard'))
    
    # Use defaults if no config exists
    defaults = AnalysisConfig()
    
    return render_template(
        'revenue_config.html',
        config=config,
        defaults=defaults
    )


# API endpoints for AJAX operations

@revenue_bp.route('/api/revenue/analysis/<int:analysis_id>')
def api_get_analysis(analysis_id: int):
    """Get analysis details as JSON."""
    analysis = RevenueAnalysis.query.get_or_404(analysis_id)
    
    return jsonify({
        'id': analysis.id,
        'customer_name': analysis.customer_name,
        'bucket': analysis.bucket,
        'category': analysis.category,
        'recommended_action': analysis.recommended_action,
        'engagement_rationale': analysis.engagement_rationale,
        'priority_score': analysis.priority_score,
        'dollars_at_risk': analysis.dollars_at_risk,
        'dollars_opportunity': analysis.dollars_opportunity,
        'avg_revenue': analysis.avg_revenue,
        'trend_slope': analysis.trend_slope,
        'confidence': analysis.confidence,
        'seller_name': analysis.seller_name,
        'tpid': analysis.tpid
    })


@revenue_bp.route('/api/revenue/stats')
def api_revenue_stats():
    """Get overall revenue analysis stats."""
    total_analyses = RevenueAnalysis.query.count()
    actionable = RevenueAnalysis.query.filter(
        RevenueAnalysis.recommended_action.notin_(["NO ACTION", "MONITOR"])
    ).count()
    
    # Category breakdown
    categories = db.session.query(
        RevenueAnalysis.category,
        db.func.count(RevenueAnalysis.id)
    ).group_by(RevenueAnalysis.category).all()
    
    return jsonify({
        'total_analyses': total_analyses,
        'actionable': actionable,
        'categories': {c: count for c, count in categories}
    })


# ============ Engagement Tracking Routes ============

@revenue_bp.route('/revenue/engagement/<int:analysis_id>', methods=['GET', 'POST'])
def record_engagement(analysis_id: int):
    """Record engagement for a revenue analysis."""
    analysis = RevenueAnalysis.query.get_or_404(analysis_id)
    
    if request.method == 'POST':
        from datetime import datetime
        
        status = request.form.get('status', 'pending')
        seller_response = request.form.get('seller_response', '').strip()
        resolution_notes = request.form.get('resolution_notes', '').strip()
        
        engagement = RevenueEngagement(
            analysis_id=analysis_id,
            assigned_to_seller=analysis.seller_name,
            category_when_sent=analysis.category,
            action_when_sent=analysis.recommended_action,
            rationale_when_sent=analysis.engagement_rationale,
            status=status
        )
        
        # Set response fields if provided
        if seller_response:
            engagement.seller_response = seller_response
            engagement.response_date = datetime.utcnow()
        
        # Set resolution fields if resolved
        if status == 'resolved' and resolution_notes:
            engagement.resolution_notes = resolution_notes
            engagement.resolved_at = datetime.utcnow()
        
        db.session.add(engagement)
        db.session.commit()
        
        flash(f'Engagement recorded for {analysis.customer_name}', 'success')
        
        # Redirect back to referrer or dashboard
        next_url = request.form.get('next', url_for('revenue.revenue_dashboard'))
        return redirect(next_url)
    
    # GET - show engagement form
    existing_engagements = RevenueEngagement.query.filter_by(
        analysis_id=analysis_id
    ).order_by(RevenueEngagement.created_at.desc()).all()
    
    return render_template('revenue_engagement.html', 
                          analysis=analysis,
                          engagements=existing_engagements)


@revenue_bp.route('/api/revenue/engagement/<int:analysis_id>', methods=['POST'])
def api_record_engagement(analysis_id: int):
    """API endpoint to record engagement (for modals)."""
    from datetime import datetime
    
    analysis = RevenueAnalysis.query.get_or_404(analysis_id)
    
    data = request.get_json() or {}
    status = data.get('status', 'pending')
    seller_response = data.get('seller_response', '')
    resolution_notes = data.get('resolution_notes', '')
    
    engagement = RevenueEngagement(
        analysis_id=analysis_id,
        assigned_to_seller=analysis.seller_name,
        category_when_sent=analysis.category,
        action_when_sent=analysis.recommended_action,
        rationale_when_sent=analysis.engagement_rationale,
        status=status
    )
    
    if seller_response:
        engagement.seller_response = seller_response
        engagement.response_date = datetime.utcnow()
    
    if status == 'resolved' and resolution_notes:
        engagement.resolution_notes = resolution_notes
        engagement.resolved_at = datetime.utcnow()
    
    db.session.add(engagement)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'engagement_id': engagement.id,
        'message': f'Engagement recorded for {analysis.customer_name}'
    })


@revenue_bp.route('/revenue/engagements')
def engagement_history():
    """View all engagement history."""
    engagements = RevenueEngagement.query.options(
        db.joinedload(RevenueEngagement.analysis)
    ).order_by(RevenueEngagement.created_at.desc()).limit(100).all()
    
    return render_template('revenue_engagement_history.html', engagements=engagements)


@revenue_bp.route('/api/revenue/engagement/<int:engagement_id>', methods=['DELETE'])
def api_delete_engagement(engagement_id: int):
    """Delete an engagement record."""
    engagement = RevenueEngagement.query.get_or_404(engagement_id)
    
    db.session.delete(engagement)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Engagement deleted'})

