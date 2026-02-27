"""
Main routes for NoteHelper.
Handles index, search, preferences, data management, and API endpoints.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response, stream_with_context, make_response, session, g
from datetime import datetime, timezone, date
from sqlalchemy import func, extract
import calendar as cal
import json
import csv
import io
import zipfile
import tempfile
import os
import re

from app.models import (db, CallLog, Customer, Seller, Territory, Topic, POD, SolutionEngineer, 
                        Vertical, UserPreference, User)

# Create blueprint
main_bp = Blueprint('main', __name__)


# =============================================================================
# Health Check Endpoint
# =============================================================================

@main_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for Azure App Service monitoring.
    Returns 200 OK if app is healthy and can connect to database.
    """
    try:
        # Test database connectivity with a simple query
        db.session.execute(db.text('SELECT 1'))
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        # Return 503 Service Unavailable if database is down
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 503


# =============================================================================
# Helper Functions
# =============================================================================

def get_seller_color(seller_id: int, use_colors: bool = True) -> str:
    """
    Generate a consistent, visually distinct color for a seller based on their ID.
    Returns a CSS color class name. If use_colors is False, returns 'bg-secondary'.
    """
    if not use_colors:
        return 'bg-secondary'
    
    # Define a palette of distinct, accessible colors
    color_classes = [
        'seller-color-1',   # Purple
        'seller-color-2',   # Teal
        'seller-color-3',   # Red
        'seller-color-4',   # Pink
        'seller-color-5',   # Blue
        'seller-color-6',   # Emerald
        'seller-color-7',   # Yellow
        'seller-color-8',   # Orange
        'seller-color-9',   # Slate
        'seller-color-10',  # Brown
    ]
    
    # Use modulo to cycle through colors if we have more sellers than colors
    color_index = (seller_id - 1) % len(color_classes)
    return color_classes[color_index]


# =============================================================================
# Main Routes
# =============================================================================

@main_bp.route('/')
def index():
    """Home page showing recent activity and stats."""
    # Check if this is a first-time user
    show_first_time_modal = session.pop('show_first_time_modal', False)
    
    # Eager load relationships for recent calls to avoid N+1 queries
    recent_calls = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).limit(10).all()
    
    # Count queries are fast on these small tables
    stats = {
        'call_logs': CallLog.query.count(),
        'customers': Customer.query.count(),
        'sellers': Seller.query.count(),
        'topics': Topic.query.count()
    }
    return render_template('index.html', recent_calls=recent_calls, stats=stats, show_first_time_modal=show_first_time_modal)


@main_bp.route('/api/call-logs/calendar')
def call_logs_calendar_api():
    """API endpoint returning call logs for calendar view.
    
    Query params:
        year: int (default: current year)
        month: int, 1-12 (default: current month)
    
    Returns JSON with:
        - year, month: the requested period
        - days: dict mapping day number -> list of {id, customer_name, customer_id}
        - month_name: human-readable month name
        - prev/next month info for navigation
    """
    today = date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    
    # Validate month range
    if month < 1 or month > 12:
        month = today.month
    
    # Get first and last day of the month
    first_day = date(year, month, 1)
    last_day = date(year, month, cal.monthrange(year, month)[1])
    
    # Query call logs for this month with customer data and relationships
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer),
        db.joinedload(CallLog.milestones)
    ).filter(
        CallLog.call_date >= first_day,
        CallLog.call_date <= last_day
    ).order_by(CallLog.call_date).all()
    
    # Group by day (call_logs already sorted by call_date from query)
    days = {}
    for log in call_logs:
        day = log.call_date.day
        if day not in days:
            days[day] = []
        days[day].append({
            'id': log.id,
            'customer_name': log.customer.name if log.customer else 'Unknown',
            'customer_id': log.customer.id if log.customer else None,
            'has_milestone': len(log.milestones) > 0,
            'has_task': log.msx_tasks.count() > 0,
            'has_hok': any(t.is_hok for t in log.msx_tasks.all()),
            'time': log.call_date.strftime('%I:%M %p').lstrip('0') if log.call_date.hour != 0 or log.call_date.minute != 0 else None
        })
    
    # Calculate prev/next month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    
    # Calendar info for rendering
    first_weekday = first_day.weekday()  # Monday = 0, Sunday = 6
    # Shift to Sunday-start week: Sunday = 0
    first_weekday = (first_weekday + 1) % 7
    days_in_month = cal.monthrange(year, month)[1]
    
    return jsonify({
        'year': year,
        'month': month,
        'month_name': cal.month_name[month],
        'days': days,
        'first_weekday': first_weekday,
        'days_in_month': days_in_month,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'today_day': today.day if today.year == year and today.month == month else None
    })


@main_bp.route('/search')
def search():
    """Search and filter call logs (FR011)."""
    # Get filter parameters
    search_text = request.args.get('q', '').strip()
    customer_id = request.args.get('customer_id', type=int)
    seller_id = request.args.get('seller_id', type=int)
    territory_id = request.args.get('territory_id', type=int)
    topic_ids = request.args.getlist('topic_ids', type=int)
    
    # Check if any search criteria provided
    has_search = bool(search_text or customer_id or seller_id or territory_id or topic_ids)
    
    call_logs = []
    grouped_data = {}
    
    # Only perform search if criteria provided
    if has_search:
        # Start with base query filtered by user
        query = CallLog.query
        
        # Apply filters
        if search_text:
            query = query.filter(CallLog.content.ilike(f'%{search_text}%'))
        
        if customer_id:
            query = query.filter(CallLog.customer_id == customer_id)
        
        if seller_id:
            query = query.join(Customer).filter(Customer.seller_id == seller_id)
        
        if territory_id:
            if not seller_id:  # Avoid duplicate join
                query = query.join(Customer)
            query = query.filter(Customer.territory_id == territory_id)
        
        if topic_ids:
            # Filter by topics (call logs that have ANY of the selected topics)
            query = query.join(CallLog.topics).filter(Topic.id.in_(topic_ids))
        
        # Get filtered call logs
        call_logs = query.order_by(CallLog.call_date.desc()).all()
        
        # Group call logs by Seller → Customer structure (FR011)
        # Structure: { seller_id: { 'seller': Seller, 'customers': { customer_id: { 'customer': Customer, 'calls': [CallLog] } } } }
        for call in call_logs:
            seller_id_key = call.seller.id if call.seller else 0  # 0 = no seller
            customer_id_key = call.customer_id if call.customer_id else 0  # 0 = no customer
            
            # Initialize seller group
            if seller_id_key not in grouped_data:
                grouped_data[seller_id_key] = {
                    'seller': call.seller,
                    'customers': {}
                }
            
            # Initialize customer group
            if customer_id_key not in grouped_data[seller_id_key]['customers']:
                grouped_data[seller_id_key]['customers'][customer_id_key] = {
                    'customer': call.customer,
                    'calls': [],
                    'most_recent_date': call.call_date
                }
            
            # Add call to customer group
            grouped_data[seller_id_key]['customers'][customer_id_key]['calls'].append(call)
            
            # Update most recent date
            if call.call_date > grouped_data[seller_id_key]['customers'][customer_id_key]['most_recent_date']:
                grouped_data[seller_id_key]['customers'][customer_id_key]['most_recent_date'] = call.call_date
        
        # Sort customers by most recent call within each seller
        for seller_id_key in grouped_data:
            customers_list = list(grouped_data[seller_id_key]['customers'].values())
            customers_list.sort(key=lambda x: x['most_recent_date'], reverse=True)
            grouped_data[seller_id_key]['customers_sorted'] = customers_list
    
    # Get all filter options for dropdowns
    customers = Customer.query.order_by(Customer.name).all()
    sellers = Seller.query.order_by(Seller.name).all()
    territories = Territory.query.order_by(Territory.name).all()
    topics = Topic.query.order_by(Topic.name).all()
    
    return render_template('search.html',
                         grouped_data=grouped_data,
                         call_logs=call_logs,
                         search_text=search_text,
                         selected_customer_id=customer_id,
                         selected_seller_id=seller_id,
                         selected_territory_id=territory_id,
                         selected_topic_ids=topic_ids,
                         customers=customers,
                         sellers=sellers,
                         territories=territories,
                         topics=topics)


@main_bp.route('/preferences')
def preferences():
    """User preferences page."""
    user_id = g.user.id if g.user.is_authenticated else 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.session.add(pref)
        db.session.commit()
    
    # Get user statistics
    stats = {
        'call_logs': CallLog.query.count(),
        'customers': Customer.query.count(),
        'topics': Topic.query.count()
    }
    
    return render_template('preferences.html', 
                         dark_mode=pref.dark_mode,
                         customer_view_grouped=pref.customer_view_grouped,
                         customer_sort_by=pref.customer_sort_by,
                         topic_sort_by_calls=pref.topic_sort_by_calls,
                         territory_view_accounts=pref.territory_view_accounts,
                         colored_sellers=pref.colored_sellers,
                         show_customers_without_calls=pref.show_customers_without_calls,
                         stats=stats)


@main_bp.route('/analytics')
def analytics():
    """Analytics and insights dashboard."""
    from datetime import date, timedelta
    from sqlalchemy import func, distinct
    
    # Date ranges
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    three_months_ago = today - timedelta(days=90)
    
    # Call volume metrics
    total_calls = CallLog.query.count()
    calls_this_week = CallLog.query.filter(
        CallLog.call_date >= week_ago
    ).count()
    calls_this_month = CallLog.query.filter(
        CallLog.call_date >= month_ago
    ).count()
    
    # Customer engagement
    total_customers = Customer.query.count()
    customers_called_this_week = db.session.query(func.count(distinct(CallLog.customer_id))).filter(
        CallLog.call_date >= week_ago
    ).scalar()
    customers_called_this_month = db.session.query(func.count(distinct(CallLog.customer_id))).filter(
        CallLog.call_date >= month_ago
    ).scalar()
    
    # Topic insights - most discussed topics
    top_topics = db.session.query(
        Topic.id,
        Topic.name,
        func.count(CallLog.id).label('call_count')
    ).join(
        CallLog.topics
    ).filter(
        CallLog.call_date >= three_months_ago
    ).group_by(
        Topic.id,
        Topic.name
    ).order_by(
        func.count(CallLog.id).desc()
    ).limit(10).all()
    
    # Customers not called recently (90+ days or never)
    customers_with_recent_calls = db.session.query(CallLog.customer_id).filter(
        CallLog.call_date >= three_months_ago
    ).distinct().subquery()
    
    customers_needing_attention = Customer.query.filter(
        ~Customer.id.in_(customers_with_recent_calls)
    ).order_by(Customer.name).limit(10).all()
    
    # Seller activity (calls per seller this month)
    seller_activity = db.session.query(
        Seller.id,
        Seller.name,
        func.count(CallLog.id).label('call_count')
    ).join(
        Customer, Customer.seller_id == Seller.id
    ).join(
        CallLog, CallLog.customer_id == Customer.id
    ).filter(
        CallLog.call_date >= month_ago
    ).group_by(
        Seller.id,
        Seller.name
    ).order_by(
        func.count(CallLog.id).desc()
    ).limit(10).all()
    
    # Call frequency trend (last 30 days, grouped by week)
    weekly_calls = []
    for i in range(4):
        week_start = today - timedelta(days=7*(i+1))
        week_end = today - timedelta(days=7*i)
        count = CallLog.query.filter(
            CallLog.call_date >= week_start,
            CallLog.call_date < week_end
        ).count()
        weekly_calls.append({
            'week_label': f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}",
            'count': count
        })
    weekly_calls.reverse()  # Show oldest to newest
    
    return render_template('analytics.html',
                         total_calls=total_calls,
                         calls_this_week=calls_this_week,
                         calls_this_month=calls_this_month,
                         total_customers=total_customers,
                         customers_called_this_week=customers_called_this_week,
                         customers_called_this_month=customers_called_this_month,
                         top_topics=top_topics,
                         customers_needing_attention=customers_needing_attention,
                         seller_activity=seller_activity,
                         weekly_calls=weekly_calls)


# =============================================================================
# My Data API Routes (User-specific exports/imports)
# =============================================================================

@main_bp.route('/api/my-data/export/call-logs-json', methods=['GET'])
def my_data_export_call_logs_json():
    """Export user's call logs to JSON (personal export)."""
    # Reuse existing call logs export but filter by current user
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
    
    # Build enriched export
    export_data = []
    for call in call_logs:
        call_data = {
            'call_date': call.call_date.isoformat() if call.call_date else None,
            'customer_name': call.customer.name if call.customer else None,
            'customer_tpid': call.customer.tpid if call.customer else None,
            'seller_name': call.customer.seller.name if call.customer and call.customer.seller else None,
            'territory_name': call.customer.territory.name if call.customer and call.customer.territory else None,
            'topics': [topic.name for topic in call.topics],
            'content': call.content,
            'created_at': call.created_at.isoformat() if call.created_at else None,
            'updated_at': call.updated_at.isoformat() if call.updated_at else None
        }
        export_data.append(call_data)
    
    # Create response
    response_data = {
        'export_date': datetime.utcnow().isoformat(),
        'user_email': g.user.email,
        'call_logs_count': len(export_data),
        'call_logs': export_data
    }
    
    response = make_response(json.dumps(response_data, indent=2))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_call_logs_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json'
    return response


@main_bp.route('/api/my-data/export/call-logs-csv', methods=['GET'])
def my_data_export_call_logs_csv():
    """Export user's call logs to CSV (personal export)."""
    # Get user's call logs
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Call Date', 'Customer Name', 'Customer TPID', 'Seller Name', 
        'Territory Name', 'Topics', 'Content (Plain Text)', 
        'Created At', 'Updated At'
    ])
    
    # Data rows
    for call in call_logs:
        # Strip HTML from content
        content_plain = re.sub('<[^<]+?>', '', call.content) if call.content else ''
        content_plain = content_plain.replace('\n', ' ').replace('\r', ' ')
        
        writer.writerow([
            call.call_date.strftime('%Y-%m-%d') if call.call_date else '',
            call.customer.name if call.customer else '',
            call.customer.tpid if call.customer else '',
            call.customer.seller.name if call.customer and call.customer.seller else '',
            call.customer.territory.name if call.customer and call.customer.territory else '',
            ', '.join([topic.name for topic in call.topics]),
            content_plain,
            call.created_at.isoformat() if call.created_at else '',
            call.updated_at.isoformat() if call.updated_at else ''
        ])
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_call_logs_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


@main_bp.route('/api/my-data/import/json', methods=['POST'])
def my_data_import_json():
    """Import call logs from JSON (personal import)."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    skip_duplicates = request.form.get('skip_duplicates', 'true').lower() == 'true'
    
    try:
        # Read and parse JSON
        data = json.load(file)
        call_logs_data = data.get('call_logs', [])
        
        imported = {'call_logs': 0, 'customers': 0, 'topics': 0}
        skipped = {'call_logs': 0, 'customers': 0, 'topics': 0}
        
        # Track created entities
        customer_map = {}  # name+tpid -> Customer object
        topic_map = {}  # name -> Topic object
        
        for call_data in call_logs_data:
            # Check for duplicate by date and customer
            customer_name = call_data.get('customer_name')
            call_date_str = call_data.get('call_date')
            
            if not customer_name or not call_date_str:
                skipped['call_logs'] += 1
                continue
            
            # Parse call_date - handle both date-only and datetime formats
            try:
                call_date = datetime.fromisoformat(call_date_str)
            except (ValueError, TypeError):
                skipped['call_logs'] += 1
                continue
            
            # Get or create customer
            customer_key = f"{customer_name}_{call_data.get('customer_tpid', '')}"
            if customer_key not in customer_map:
                # Check if customer exists
                existing_customer = Customer.query.filter_by(
                    name=customer_name,
                    tpid=call_data.get('customer_tpid')
                ).first()
                
                if existing_customer:
                    customer_map[customer_key] = existing_customer
                else:
                    # Create new customer
                    new_customer = Customer(
                        name=customer_name,
                        tpid=call_data.get('customer_tpid', '')
                    )
                    db.session.add(new_customer)
                    db.session.flush()  # Get ID without committing
                    customer_map[customer_key] = new_customer
                    imported['customers'] += 1
            
            customer = customer_map[customer_key]
            
            # Check for duplicate call log
            if skip_duplicates:
                existing_call = CallLog.query.filter_by(
                    customer_id=customer.id,
                    call_date=call_date
                ).first()
                
                if existing_call:
                    skipped['call_logs'] += 1
                    continue
            
            # Create call log
            new_call = CallLog(
                customer_id=customer.id,
                call_date=call_date,
                content=call_data.get('content', ''),
                user_id=g.user.id,
                created_at=datetime.fromisoformat(call_data['created_at']) if call_data.get('created_at') else datetime.utcnow(),
                updated_at=datetime.fromisoformat(call_data['updated_at']) if call_data.get('updated_at') else datetime.utcnow()
            )
            
            # Add topics
            for topic_name in call_data.get('topics', []):
                if topic_name not in topic_map:
                    # Check if topic exists
                    existing_topic = Topic.query.filter_by(
                        name=topic_name
                    ).first()
                    
                    if existing_topic:
                        topic_map[topic_name] = existing_topic
                    else:
                        # Create new topic
                        new_topic = Topic(
                            name=topic_name
                        )
                        db.session.add(new_topic)
                        db.session.flush()
                        topic_map[topic_name] = new_topic
                        imported['topics'] += 1
                
                new_call.topics.append(topic_map[topic_name])
            
            db.session.add(new_call)
            imported['call_logs'] += 1
        
        # Commit all changes
        db.session.commit()
        
        return jsonify({
            'success': True,
            'imported': imported,
            'skipped': skipped
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# Data Management API Routes (Admin only)
# =============================================================================

@main_bp.route('/api/data-management/stats', methods=['GET'])
def data_management_stats():
    """Get database statistics for data management page."""
    stats = {
        'pods': POD.query.count(),
        'territories': Territory.query.count(),
        'sellers': Seller.query.count(),
        'solution_engineers': SolutionEngineer.query.count(),
        'customers': Customer.query.count(),
        'verticals': Vertical.query.count(),
        'topics': Topic.query.count(),
        'call_logs': CallLog.query.count()
    }
    return jsonify(stats), 200


@main_bp.route('/api/data-management/clear', methods=['POST'])
def data_management_clear():
    """Clear all data from the database."""
    try:
        # Delete in correct order to handle foreign key constraints
        # Delete association tables first
        db.session.execute(db.text('DELETE FROM call_logs_topics'))
        db.session.execute(db.text('DELETE FROM customers_verticals'))
        db.session.execute(db.text('DELETE FROM sellers_territories'))
        db.session.execute(db.text('DELETE FROM solution_engineers_pods'))
        
        # Delete dependent tables
        CallLog.query.delete()
        Customer.query.delete()
        Topic.query.delete()
        Vertical.query.delete()
        SolutionEngineer.query.delete()
        Seller.query.delete()
        
        # Delete parent tables
        Territory.query.delete()
        POD.query.delete()
        
        db.session.commit()
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main_bp.route('/api/data-management/import', methods=['POST'])
def data_management_import():
    """Import alignment sheet CSV with real-time progress feedback."""
    if 'file' not in request.files:
        return {'error': 'No file uploaded'}, 400
    
    file = request.files['file']
    
    if file.filename == '':
        return {'error': 'No file selected'}, 400
    
    if not file.filename.endswith('.csv'):
        return {'error': 'File must be a CSV'}, 400
    
    def generate():
        """Generator function to stream progress updates."""
        temp_path = None
        try:
            # Send progress message
            yield "data: " + json.dumps({"message": "Saving uploaded file..."}) + "\n\n"
            
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.csv') as temp_file:
                file.save(temp_file.name)
                temp_path = temp_file.name
            
            yield "data: " + json.dumps({"message": "Reading CSV file..."}) + "\n\n"
            
            # Read CSV with multiple encoding attempts
            encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
            rows = None
            
            for encoding in encodings:
                try:
                    with open(temp_path, 'r', encoding=encoding) as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                    msg = f"Successfully read CSV with {encoding} encoding ({len(rows)} rows)"
                    yield "data: " + json.dumps({"message": msg}) + "\n\n"
                    break
                except UnicodeDecodeError:
                    continue
            
            if rows is None:
                yield "data: " + json.dumps({"error": "Could not read CSV file"}) + "\n\n"
                return
            
            # Track created entities
            territories_map = {}
            sellers_map = {}
            pods_map = {}
            solution_engineers_map = {}
            verticals_map = {}
            
            yield "data: " + json.dumps({"message": "Processing territories..."}) + "\n\n"
            
            # Create Territories
            territory_names = set(row.get('Sales Territory', '').strip() for row in rows if row.get('Sales Territory', '').strip())
            for territory_name in territory_names:
                existing = Territory.query.filter_by(name=territory_name).first()
                if existing:
                    territories_map[territory_name] = existing
                else:
                    territory = Territory(name=territory_name, user_id=g.user.id)
                    db.session.add(territory)
                    territories_map[territory_name] = territory
            
            db.session.flush()
            msg = f"Created/found {len(territories_map)} territories"
            yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Processing sellers..."}) + "\n\n"
            
            # Create Sellers
            seller_names = set(row.get('DSS (Growth/Acq)', '').strip() for row in rows if row.get('DSS (Growth/Acq)', '').strip())
            for seller_name in seller_names:
                existing = Seller.query.filter_by(name=seller_name).first()
                if existing:
                    sellers_map[seller_name] = existing
                else:
                    seller_row = next((r for r in rows if r.get('DSS (Growth/Acq)', '').strip() == seller_name), None)
                    if seller_row:
                        growth_dss = seller_row.get('Primary Cloud & AI DSS', '').strip()
                        acq_dss = seller_row.get('Primary Cloud & AI-Acq DSS', '').strip()
                        
                        if growth_dss:
                            seller_type = 'Growth'
                            alias = growth_dss.lower()
                        elif acq_dss:
                            seller_type = 'Acquisition'
                            alias = acq_dss.lower()
                        else:
                            seller_type = 'Growth'
                            alias = None
                        
                        seller = Seller(name=seller_name, seller_type=seller_type, alias=alias, user_id=g.user.id)
                        db.session.add(seller)
                        sellers_map[seller_name] = seller
            
            db.session.flush()
            msg = f"Created/found {len(sellers_map)} sellers"
            yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Associating sellers with territories..."}) + "\n\n"
            
            # Associate Sellers with Territories
            for row in rows:
                seller_name = row.get('DSS (Growth/Acq)', '').strip()
                territory_name = row.get('Sales Territory', '').strip()
                if seller_name and territory_name:
                    seller = sellers_map.get(seller_name)
                    territory = territories_map.get(territory_name)
                    if seller and territory and territory not in seller.territories:
                        seller.territories.append(territory)
            
            db.session.flush()
            yield "data: " + json.dumps({"message": "Seller-territory associations complete"}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Processing PODs..."}) + "\n\n"
            
            # Create PODs
            pod_names = set(row.get('SME&C POD', '').strip() for row in rows if row.get('SME&C POD', '').strip())
            for pod_name in pod_names:
                existing = POD.query.filter_by(name=pod_name).first()
                if existing:
                    pods_map[pod_name] = existing
                else:
                    pod = POD(name=pod_name, user_id=g.user.id)
                    db.session.add(pod)
                    pods_map[pod_name] = pod
            
            db.session.flush()
            msg = f"Created/found {len(pods_map)} PODs"
            yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Associating territories with PODs..."}) + "\n\n"
            
            # Associate Territories with PODs
            for territory_name, territory in territories_map.items():
                territory_row = next((r for r in rows if r.get('Sales Territory', '').strip() == territory_name), None)
                if territory_row:
                    pod_name = territory_row.get('SME&C POD', '').strip()
                    if pod_name and not territory.pod:
                        territory.pod = pods_map.get(pod_name)
            
            db.session.flush()
            yield "data: " + json.dumps({"message": "Territory-POD associations complete"}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Processing solution engineers (Data)..."}) + "\n\n"
            
            # Create Solution Engineers - Data
            data_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
            for row in rows:
                se_name = row.get('Data SE', '').strip()
                if se_name:
                    if se_name not in data_se_info:
                        alias = row.get('Primary Cloud & AI Data DSE', '').strip().lower()
                        data_se_info[se_name] = {'alias': alias, 'pods': set()}
                    pod_name = row.get('SME&C POD', '').strip()
                    if pod_name and pod_name in pods_map:
                        data_se_info[se_name]['pods'].add(pod_name)
            
            for se_name, info in data_se_info.items():
                existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Data').first()
                if existing:
                    solution_engineers_map[se_name] = existing
                    # Update POD associations for existing SE
                    for pod_name in info['pods']:
                        pod = pods_map.get(pod_name)
                        if pod and pod not in existing.pods:
                            existing.pods.append(pod)
                else:
                    se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Data', user_id=g.user.id)
                    for pod_name in info['pods']:
                        se.pods.append(pods_map[pod_name])
                    db.session.add(se)
                    solution_engineers_map[se_name] = se
            
            yield "data: " + json.dumps({"message": "Processing solution engineers (Infra)..."}) + "\n\n"
            
            # Create Solution Engineers - Infra
            infra_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
            for row in rows:
                se_name = row.get('Infra SE', '').strip()
                if se_name:
                    if se_name not in infra_se_info:
                        alias = row.get('Primary Cloud & AI Infrastructure DSE', '').strip().lower()
                        infra_se_info[se_name] = {'alias': alias, 'pods': set()}
                    pod_name = row.get('SME&C POD', '').strip()
                    if pod_name and pod_name in pods_map:
                        infra_se_info[se_name]['pods'].add(pod_name)
            
            for se_name, info in infra_se_info.items():
                existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Core and Infra').first()
                if existing:
                    solution_engineers_map[se_name] = existing
                    # Update POD associations for existing SE
                    for pod_name in info['pods']:
                        pod = pods_map.get(pod_name)
                        if pod and pod not in existing.pods:
                            existing.pods.append(pod)
                else:
                    se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Core and Infra', user_id=g.user.id)
                    for pod_name in info['pods']:
                        se.pods.append(pods_map[pod_name])
                    db.session.add(se)
                    solution_engineers_map[se_name] = se
            
            yield "data: " + json.dumps({"message": "Processing solution engineers (Apps)..."}) + "\n\n"
            
            # Create Solution Engineers - Apps
            apps_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
            for row in rows:
                se_name = row.get('Apps SE', '').strip()
                if se_name:
                    if se_name not in apps_se_info:
                        alias = row.get('Primary Cloud & AI Apps DSE', '').strip().lower()
                        apps_se_info[se_name] = {'alias': alias, 'pods': set()}
                    pod_name = row.get('SME&C POD', '').strip()
                    if pod_name and pod_name in pods_map:
                        apps_se_info[se_name]['pods'].add(pod_name)
            
            for se_name, info in apps_se_info.items():
                existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Apps and AI').first()
                if existing:
                    solution_engineers_map[se_name] = existing
                    # Update POD associations for existing SE
                    for pod_name in info['pods']:
                        pod = pods_map.get(pod_name)
                        if pod and pod not in existing.pods:
                            existing.pods.append(pod)
                else:
                    se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Apps and AI', user_id=g.user.id)
                    for pod_name in info['pods']:
                        se.pods.append(pods_map[pod_name])
                    db.session.add(se)
                    solution_engineers_map[se_name] = se
            
            db.session.flush()
            msg = f"Created/found {len(solution_engineers_map)} solution engineers"
            yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Processing verticals..."}) + "\n\n"
            
            # Create Verticals - collect all unique vertical names from both columns
            vertical_names = set()
            for row in rows:
                vertical = row.get('Vertical', '').strip()
                category = row.get('Vertical Category', '').strip()
                # Add Vertical if not N/A
                if vertical and vertical.upper() != 'N/A':
                    vertical_names.add(vertical)
                # Add Vertical Category as separate vertical if not N/A
                if category and category.upper() != 'N/A':
                    vertical_names.add(category)
            
            for vertical_name in vertical_names:
                existing = Vertical.query.filter_by(name=vertical_name).first()
                if existing:
                    verticals_map[vertical_name] = existing
                else:
                    vertical = Vertical(name=vertical_name, user_id=g.user.id)
                    db.session.add(vertical)
                    verticals_map[vertical_name] = vertical
            
            db.session.flush()
            msg = f"Created/found {len(verticals_map)} verticals"
            yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Processing customers..."}) + "\n\n"
            
            # Create Customers
            customers_created = 0
            customers_skipped = 0
            total_rows = len(rows)
            
            for idx, row in enumerate(rows, 1):
                customer_name = row.get('Customer Name', '').strip()
                tpid_str = row.get('TPID', '').strip()
                
                if not customer_name or not tpid_str:
                    customers_skipped += 1
                    continue
                
                try:
                    tpid = int(tpid_str)
                except ValueError:
                    customers_skipped += 1
                    continue
                
                existing = Customer.query.filter_by(tpid=tpid).first()
                if existing:
                    customers_skipped += 1
                    continue
                
                territory_name = row.get('Sales Territory', '').strip()
                seller_name = row.get('DSS (Growth/Acq)', '').strip()
                vertical_name = row.get('Vertical', '').strip()
                category = row.get('Vertical Category', '').strip()
                
                customer = Customer(
                    name=customer_name,
                    tpid=tpid,
                    territory=territories_map.get(territory_name),
                    seller=sellers_map.get(seller_name),
                    user_id=g.user.id)
                
                # Associate both verticals if they exist and aren't N/A
                if vertical_name and vertical_name.upper() != 'N/A':
                    vertical = verticals_map.get(vertical_name)
                    if vertical:
                        customer.verticals.append(vertical)
                
                if category and category.upper() != 'N/A':
                    vertical = verticals_map.get(category)
                    if vertical and vertical not in customer.verticals:
                        customer.verticals.append(vertical)
                
                db.session.add(customer)
                customers_created += 1
                
                # Progress update every 50 customers
                if idx % 50 == 0:
                    msg = f"Processed {idx}/{total_rows} rows ({customers_created} created, {customers_skipped} skipped)"
                    yield "data: " + json.dumps({"message": msg}) + "\n\n"
            
            yield "data: " + json.dumps({"message": "Committing changes to database..."}) + "\n\n"
            db.session.commit()
            
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            
            # Send final success message
            result = {
                'pods': len(pods_map),
                'territories': len(territories_map),
                'sellers': len(sellers_map),
                'solution_engineers': len(solution_engineers_map),
                'verticals': len(verticals_map),
                'customers_created': customers_created,
                'customers_skipped': customers_skipped
            }
            yield "data: " + json.dumps({"message": "Import complete!", "result": result}) + "\n\n"
            
        except Exception as e:
            db.session.rollback()
            # Clean up temp file on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            yield "data: " + json.dumps({"error": str(e)}) + "\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@main_bp.route('/api/data-management/export/json', methods=['GET'])
def export_full_json():
    """Export complete database as JSON for disaster recovery."""
    from app.models import UserPreference, AIConfig
    
    # Check if AI config should be excluded
    exclude_ai_config = request.args.get('exclude_ai_config', 'false').lower() == 'true'
    
    # Export AI config if it exists and not excluded
    ai_config_data = None
    if not exclude_ai_config:
        ai_config = AIConfig.query.first()
        if ai_config:
            ai_config_data = {
                'enabled': ai_config.enabled,
                'endpoint_url': ai_config.endpoint_url,
                'api_key': ai_config.api_key,
                'deployment_name': ai_config.deployment_name,
                'api_version': ai_config.api_version,
                'system_prompt': ai_config.system_prompt
            }
    
    data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'version': '2.1',  # Bumped version to include user preferences and AI config
        'users': [{'id': u.id, 'microsoft_azure_id': u.microsoft_azure_id, 
                   'external_azure_id': u.external_azure_id, 'email': u.email,
                   'microsoft_email': u.microsoft_email, 'external_email': u.external_email,
                   'name': u.name, 'is_admin': u.is_admin} for u in User.query.all()],
        'user_preferences': [{'user_id': p.user_id, 'dark_mode': p.dark_mode, 
                             'customer_view_grouped': p.customer_view_grouped,
                             'topic_sort_by_calls': p.topic_sort_by_calls,
                             'territory_view_accounts': p.territory_view_accounts,
                             'colored_sellers': p.colored_sellers} for p in UserPreference.query.all()],
        'ai_config': ai_config_data,
        'pods': [{'id': p.id, 'name': p.name, 'user_id': p.user_id} for p in POD.query.all()],
        'territories': [{'id': t.id, 'name': t.name, 'pod_id': t.pod_id, 'user_id': t.user_id} for t in Territory.query.all()],
        'sellers': [{'id': s.id, 'name': s.name, 'alias': s.alias, 'seller_type': s.seller_type, 
                     'user_id': s.user_id, 'territory_ids': [t.id for t in s.territories]} for s in Seller.query.all()],
        'solution_engineers': [{'id': se.id, 'name': se.name, 'alias': se.alias, 'specialty': se.specialty,
                               'user_id': se.user_id, 'pod_ids': [p.id for p in se.pods]} for se in SolutionEngineer.query.all()],
        'verticals': [{'id': v.id, 'name': v.name, 'user_id': v.user_id} for v in Vertical.query.all()],
        'customers': [{'id': c.id, 'name': c.name, 'nickname': c.nickname, 'tpid': c.tpid, 
                       'tpid_url': c.tpid_url, 'territory_id': c.territory_id, 'seller_id': c.seller_id,
                       'user_id': c.user_id, 'vertical_ids': [v.id for v in c.verticals]} for c in Customer.query.all()],
        'topics': [{'id': t.id, 'name': t.name, 'description': t.description, 'user_id': t.user_id} for t in Topic.query.all()],
        'call_logs': [{'id': cl.id, 'customer_id': cl.customer_id,
                       'call_date': cl.call_date.isoformat(),
                       'content': cl.content, 'topic_ids': [t.id for t in cl.topics],
                       'user_id': cl.user_id, 'created_at': cl.created_at.isoformat()} for cl in CallLog.query.all()]
    }
    
    response = current_app.response_class(
        response=json.dumps(data, indent=2),
        status=200,
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_backup_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json'
    return response


@main_bp.route('/api/data-management/import/json', methods=['POST'])
def import_full_json():
    """Import complete database from JSON backup file.
    
    Matches users by Azure Object IDs to preserve ownership.
    Creates new users if they don't exist.
    """
    if 'file' not in request.files:
        return {'error': 'No file uploaded'}, 400
    
    file = request.files['file']
    
    if file.filename == '':
        return {'error': 'No file selected'}, 400
    
    if not file.filename.endswith('.json'):
        return {'error': 'File must be JSON'}, 400
    
    try:
        data = json.load(file)
    except json.JSONDecodeError:
        return {'error': 'Invalid JSON file'}, 400
    
    # Validate required keys
    required_keys = ['version', 'users', 'pods', 'territories', 'sellers', 
                     'solution_engineers', 'verticals', 'customers', 'topics', 'call_logs']
    missing_keys = [k for k in required_keys if k not in data]
    if missing_keys:
        return {'error': f'Missing required keys: {", ".join(missing_keys)}'}, 400
    
    try:
        # Track ID mappings (old_id -> new_object)
        user_map = {}
        pod_map = {}
        territory_map = {}
        seller_map = {}
        se_map = {}
        vertical_map = {}
        customer_map = {}
        topic_map = {}
        
        # Track created vs matched users
        created_users = 0
        
        # Import users first - match by Azure Object IDs
        for user_data in data['users']:
            # Try to find existing user by Azure IDs
            existing_user = None
            if user_data.get('microsoft_azure_id'):
                existing_user = User.query.filter_by(microsoft_azure_id=user_data['microsoft_azure_id']).first()
            if not existing_user and user_data.get('external_azure_id'):
                existing_user = User.query.filter_by(external_azure_id=user_data['external_azure_id']).first()
            
            if existing_user:
                # User already exists - update email fields if needed
                if user_data.get('microsoft_email'):
                    existing_user.microsoft_email = user_data['microsoft_email']
                if user_data.get('external_email'):
                    existing_user.external_email = user_data['external_email']
                user_map[user_data['id']] = existing_user
            else:
                # Create new user (stub account that will be linked on first login)
                new_user = User(
                    microsoft_azure_id=user_data.get('microsoft_azure_id'),
                    external_azure_id=user_data.get('external_azure_id'),
                    email=user_data['email'],
                    microsoft_email=user_data.get('microsoft_email'),
                    external_email=user_data.get('external_email'),
                    name=user_data['name'],
                    is_admin=user_data.get('is_admin', False),
                    is_stub=True  # Mark as stub until they log in
                )
                db.session.add(new_user)
                db.session.flush()
                user_map[user_data['id']] = new_user
                created_users += 1
        
        # Import PODs
        for pod_data in data['pods']:
            new_user_id = user_map[pod_data['user_id']].id
            pod = POD(name=pod_data['name'], user_id=new_user_id)
            db.session.add(pod)
            db.session.flush()
            pod_map[pod_data['id']] = pod
        
        # Import Territories
        for territory_data in data['territories']:
            new_user_id = user_map[territory_data['user_id']].id
            pod_id = pod_map[territory_data['pod_id']].id if territory_data.get('pod_id') else None
            territory = Territory(name=territory_data['name'], pod_id=pod_id, user_id=new_user_id)
            db.session.add(territory)
            db.session.flush()
            territory_map[territory_data['id']] = territory
        
        # Import Sellers
        for seller_data in data['sellers']:
            new_user_id = user_map[seller_data['user_id']].id
            seller = Seller(
                name=seller_data['name'],
                alias=seller_data.get('alias'),
                seller_type=seller_data['seller_type'],
                user_id=new_user_id
            )
            # Add territory associations
            for territory_id in seller_data.get('territory_ids', []):
                if territory_id in territory_map:
                    seller.territories.append(territory_map[territory_id])
            db.session.add(seller)
            db.session.flush()
            seller_map[seller_data['id']] = seller
        
        # Import Solution Engineers
        for se_data in data['solution_engineers']:
            new_user_id = user_map[se_data['user_id']].id
            se = SolutionEngineer(
                name=se_data['name'],
                alias=se_data.get('alias'),
                specialty=se_data.get('specialty'),
                user_id=new_user_id
            )
            # Add POD associations
            for pod_id in se_data.get('pod_ids', []):
                if pod_id in pod_map:
                    se.pods.append(pod_map[pod_id])
            db.session.add(se)
            db.session.flush()
            se_map[se_data['id']] = se
        
        # Import Verticals
        for vertical_data in data['verticals']:
            new_user_id = user_map[vertical_data['user_id']].id
            vertical = Vertical(name=vertical_data['name'], user_id=new_user_id)
            db.session.add(vertical)
            db.session.flush()
            vertical_map[vertical_data['id']] = vertical
        
        # Import Customers
        for customer_data in data['customers']:
            new_user_id = user_map[customer_data['user_id']].id
            territory_id = territory_map[customer_data['territory_id']].id if customer_data.get('territory_id') else None
            seller_id = seller_map[customer_data['seller_id']].id if customer_data.get('seller_id') else None
            
            customer = Customer(
                name=customer_data['name'],
                nickname=customer_data.get('nickname'),
                tpid=customer_data['tpid'],
                tpid_url=customer_data.get('tpid_url'),
                territory_id=territory_id,
                seller_id=seller_id,
                user_id=new_user_id
            )
            # Add vertical associations
            for vertical_id in customer_data.get('vertical_ids', []):
                if vertical_id in vertical_map:
                    customer.verticals.append(vertical_map[vertical_id])
            db.session.add(customer)
            db.session.flush()
            customer_map[customer_data['id']] = customer
        
        # Import Topics
        for topic_data in data['topics']:
            new_user_id = user_map[topic_data['user_id']].id
            topic = Topic(
                name=topic_data['name'],
                description=topic_data.get('description'),
                user_id=new_user_id
            )
            db.session.add(topic)
            db.session.flush()
            topic_map[topic_data['id']] = topic
        
        # Import Call Logs
        for cl_data in data['call_logs']:
            new_user_id = user_map[cl_data['user_id']].id
            customer_id = customer_map[cl_data['customer_id']].id
            
            call_log = CallLog(
                customer_id=customer_id,
                call_date=datetime.fromisoformat(cl_data['call_date']) if isinstance(cl_data['call_date'], str) else cl_data['call_date'],
                content=cl_data['content'],
                user_id=new_user_id,
                created_at=datetime.fromisoformat(cl_data['created_at']) if isinstance(cl_data.get('created_at'), str) else datetime.utcnow()
            )
            # Add topic associations
            for topic_id in cl_data.get('topic_ids', []):
                if topic_id in topic_map:
                    call_log.topics.append(topic_map[topic_id])
            db.session.add(call_log)
        
        # Import User Preferences (if present in export)
        imported_prefs = 0
        if 'user_preferences' in data:
            from app.models import UserPreference
            for pref_data in data['user_preferences']:
                old_user_id = pref_data['user_id']
                if old_user_id in user_map:
                    new_user = user_map[old_user_id]
                    # Check if preference already exists
                    existing_pref = UserPreference.query.filter_by(user_id=new_user.id).first()
                    if existing_pref:
                        # Update existing preferences
                        existing_pref.dark_mode = pref_data.get('dark_mode', False)
                        existing_pref.customer_view_grouped = pref_data.get('customer_view_grouped', False)
                        existing_pref.topic_sort_by_calls = pref_data.get('topic_sort_by_calls', False)
                        existing_pref.territory_view_accounts = pref_data.get('territory_view_accounts', False)
                        existing_pref.colored_sellers = pref_data.get('colored_sellers', True)
                    else:
                        # Create new preferences
                        new_pref = UserPreference(
                            user_id=new_user.id,
                            dark_mode=pref_data.get('dark_mode', False),
                            customer_view_grouped=pref_data.get('customer_view_grouped', False),
                            topic_sort_by_calls=pref_data.get('topic_sort_by_calls', False),
                            territory_view_accounts=pref_data.get('territory_view_accounts', False),
                            colored_sellers=pref_data.get('colored_sellers', True)
                        )
                        db.session.add(new_pref)
                    imported_prefs += 1
        
        # Import AI Config (if present in export)
        imported_ai_config = False
        if data.get('ai_config'):
            from app.models import AIConfig
            ai_data = data['ai_config']
            
            # Check if AI config already exists
            existing_config = AIConfig.query.first()
            if existing_config:
                # Update existing config
                existing_config.enabled = ai_data.get('enabled', False)
                existing_config.endpoint_url = ai_data.get('endpoint_url')
                existing_config.api_key = ai_data.get('api_key')
                existing_config.deployment_name = ai_data.get('deployment_name')
                existing_config.api_version = ai_data.get('api_version', '2024-08-01-preview')
                existing_config.system_prompt = ai_data.get('system_prompt', existing_config.system_prompt)
            else:
                # Create new config
                new_config = AIConfig(
                    enabled=ai_data.get('enabled', False),
                    endpoint_url=ai_data.get('endpoint_url'),
                    api_key=ai_data.get('api_key'),
                    deployment_name=ai_data.get('deployment_name'),
                    api_version=ai_data.get('api_version', '2024-08-01-preview'),
                    system_prompt=ai_data.get('system_prompt')
                )
                db.session.add(new_config)
            imported_ai_config = True
        
        db.session.commit()
        
        message = f'Successfully imported {created_users} users, {len(pod_map)} PODs, ' \
                  f'{len(territory_map)} territories, {len(seller_map)} sellers, ' \
                  f'{len(customer_map)} customers, {len(topic_map)} topics, ' \
                  f'{len(data["call_logs"])} call logs'
        
        if imported_prefs > 0:
            message += f', {imported_prefs} user preferences'
        if imported_ai_config:
            message += ', AI config'
        
        return {
            'success': True,
            'message': message
        }, 200
        
    except Exception as e:
        db.session.rollback()
        return {'error': f'Import failed: {str(e)}'}, 500


@main_bp.route('/api/data-management/export/csv', methods=['GET'])
def export_full_csv():
    """Export complete database as CSV files in ZIP for spreadsheet analysis."""
    # Create in-memory ZIP file
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # PODs
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name'])
        for p in POD.query.all():
            writer.writerow([p.id, p.name])
        zip_file.writestr('pods.csv', csv_buffer.getvalue())
        
        # Territories
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name', 'pod_id', 'pod_name'])
        for t in Territory.query.options(db.joinedload(Territory.pod)).all():
            writer.writerow([t.id, t.name, t.pod_id, t.pod.name if t.pod else ''])
        zip_file.writestr('territories.csv', csv_buffer.getvalue())
        
        # Sellers
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name', 'alias', 'seller_type', 'territories'])
        for s in Seller.query.all():
            territories = ', '.join([t.name for t in s.territories])
            writer.writerow([s.id, s.name, s.alias, s.seller_type, territories])
        zip_file.writestr('sellers.csv', csv_buffer.getvalue())
        
        # Solution Engineers
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name', 'alias', 'specialty', 'pods'])
        for se in SolutionEngineer.query.all():
            pods = ', '.join([p.name for p in se.pods])
            writer.writerow([se.id, se.name, se.alias, se.specialty, pods])
        zip_file.writestr('solution_engineers.csv', csv_buffer.getvalue())
        
        # Verticals
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name'])
        for v in Vertical.query.all():
            writer.writerow([v.id, v.name])
        zip_file.writestr('verticals.csv', csv_buffer.getvalue())
        
        # Customers
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name', 'nickname', 'tpid', 'tpid_url', 'territory', 'seller', 'verticals'])
        for c in Customer.query.options(
            db.joinedload(Customer.territory),
            db.joinedload(Customer.seller)
        ).all():
            verticals = ', '.join([v.name for v in c.verticals])
            writer.writerow([c.id, c.name, c.nickname, c.tpid, c.tpid_url,
                           c.territory.name if c.territory else '',
                           c.seller.name if c.seller else '',
                           verticals])
        zip_file.writestr('customers.csv', csv_buffer.getvalue())
        
        # Topics
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'name', 'description'])
        for t in Topic.query.all():
            writer.writerow([t.id, t.name, t.description])
        zip_file.writestr('topics.csv', csv_buffer.getvalue())
        
        # Call Logs
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['id', 'call_date', 'customer', 'seller', 'territory', 'content', 'topics', 'created_at'])
        for cl in CallLog.query.options(
            db.joinedload(CallLog.customer).joinedload(Customer.seller),
            db.joinedload(CallLog.customer).joinedload(Customer.territory)
        ).all():
            topics = ', '.join([t.name for t in cl.topics])
            writer.writerow([cl.id, cl.call_date.isoformat(),
                           cl.customer.name if cl.customer else '',
                           cl.seller.name if cl.seller else '',
                           cl.territory.name if cl.territory else '',
                           cl.content, topics, cl.created_at.isoformat()])
        zip_file.writestr('call_logs.csv', csv_buffer.getvalue())
    
    zip_buffer.seek(0)
    response = current_app.response_class(
        response=zip_buffer.getvalue(),
        status=200,
        mimetype='application/zip'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_backup_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.zip'
    return response


@main_bp.route('/api/data-management/export/call-logs-json', methods=['GET'])
def export_call_logs_json():
    """Export call logs with enriched data as JSON for external analysis/LLM processing."""
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.verticals),
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory).joinedload(Territory.pod)
    ).order_by(CallLog.call_date.desc()).all()
    
    data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'export_type': 'call_logs',
        'total_calls': len(call_logs),
        'call_logs': []
    }
    
    for cl in call_logs:
        call_data = {
            'id': cl.id,
            'call_date': cl.call_date.isoformat(),
            'content': cl.content,
            'customer': {
                'name': cl.customer.name if cl.customer else None,
                'nickname': cl.customer.nickname if cl.customer else None,
                'tpid': cl.customer.tpid if cl.customer else None,
                'verticals': [v.name for v in cl.customer.verticals] if cl.customer else []
            },
            'seller': {
                'name': cl.seller.name if cl.seller else None,
                'alias': cl.seller.alias if cl.seller else None,
                'email': f"{cl.seller.alias}@microsoft.com" if cl.seller and cl.seller.alias else None,
                'type': cl.seller.seller_type if cl.seller else None
            },
            'territory': {
                'name': cl.territory.name if cl.territory else None,
                'pod': cl.territory.pod.name if cl.territory and cl.territory.pod else None
            },
            'topics': [t.name for t in cl.topics],
            'created_at': cl.created_at.isoformat()
        }
        data['call_logs'].append(call_data)
    
    response = current_app.response_class(
        response=json.dumps(data, indent=2),
        status=200,
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=call_logs_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json'
    return response


@main_bp.route('/api/data-management/export/call-logs-csv', methods=['GET'])
def export_call_logs_csv():
    """Export call logs with enriched data as CSV for spreadsheet analysis."""
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.verticals),
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory).joinedload(Territory.pod)
    ).order_by(CallLog.call_date.desc()).all()
    
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    
    # Header
    writer.writerow([
        'Call Date', 'Customer Name', 'Customer Nickname', 'Customer TPID', 'Customer Verticals',
        'Seller Name', 'Seller Email', 'Seller Type',
        'Territory', 'POD',
        'Topics', 'Call Content', 'Created At'
    ])
    
    # Data
    for cl in call_logs:
        writer.writerow([
            cl.call_date.strftime('%Y-%m-%d'),
            cl.customer.name if cl.customer else '',
            cl.customer.nickname if cl.customer else '',
            cl.customer.tpid if cl.customer else '',
            ', '.join([v.name for v in cl.customer.verticals]) if cl.customer else '',
            cl.seller.name if cl.seller else '',
            f"{cl.seller.alias}@microsoft.com" if cl.seller and cl.seller.alias else '',
            cl.seller.seller_type if cl.seller else '',
            cl.territory.name if cl.territory else '',
            cl.territory.pod.name if cl.territory and cl.territory.pod else '',
            ', '.join([t.name for t in cl.topics]),
            cl.content,
            cl.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    response = current_app.response_class(
        response=csv_buffer.getvalue(),
        status=200,
        mimetype='text/csv'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=call_logs_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# =============================================================================
# Preferences API Routes
# =============================================================================

@main_bp.route('/api/preferences/dark-mode', methods=['GET', 'POST'])
def dark_mode_preference():
    """Get or set dark mode preference."""
    # Get user ID (handle testing mode where login is disabled)
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        dark_mode = data.get('dark_mode', False)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, dark_mode=dark_mode)
            db.session.add(pref)
        else:
            pref.dark_mode = dark_mode
        
        db.session.commit()
        return jsonify({'dark_mode': pref.dark_mode}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, dark_mode=False)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'dark_mode': pref.dark_mode}), 200


@main_bp.route('/api/preferences/customer-view', methods=['GET', 'POST'])
def customer_view_preference():
    """Get or set customer view preference (alphabetical vs grouped)."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        customer_view_grouped = data.get('customer_view_grouped', False)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, customer_view_grouped=customer_view_grouped)
            db.session.add(pref)
        else:
            pref.customer_view_grouped = customer_view_grouped
        
        db.session.commit()
        return jsonify({'customer_view_grouped': pref.customer_view_grouped}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, customer_view_grouped=False)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'customer_view_grouped': pref.customer_view_grouped}), 200


@main_bp.route('/api/preferences/topic-sort', methods=['GET', 'POST'])
def topic_sort_preference():
    """Get or set topic sort preference (alphabetical vs by calls)."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        topic_sort_by_calls = data.get('topic_sort_by_calls', False)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, topic_sort_by_calls=topic_sort_by_calls)
            db.session.add(pref)
        else:
            pref.topic_sort_by_calls = topic_sort_by_calls
        
        db.session.commit()
        return jsonify({'topic_sort_by_calls': pref.topic_sort_by_calls}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, topic_sort_by_calls=False)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'topic_sort_by_calls': pref.topic_sort_by_calls}), 200


@main_bp.route('/api/preferences/territory-view', methods=['GET', 'POST'])
def territory_view_preference():
    """Get or set territory view preference (recent calls vs accounts)."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        territory_view_accounts = data.get('territory_view_accounts', False)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, territory_view_accounts=territory_view_accounts)
            db.session.add(pref)
        else:
            pref.territory_view_accounts = territory_view_accounts
        
        db.session.commit()
        return jsonify({'territory_view_accounts': pref.territory_view_accounts}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, territory_view_accounts=False)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'territory_view_accounts': pref.territory_view_accounts}), 200


@main_bp.route('/api/preferences/colored-sellers', methods=['GET', 'POST'])
def colored_sellers_preference():
    """Get or set colored sellers preference (grey vs colored badges)."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        colored_sellers = data.get('colored_sellers', True)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, colored_sellers=colored_sellers)
            db.session.add(pref)
        else:
            pref.colored_sellers = colored_sellers
        
        db.session.commit()
        return jsonify({'colored_sellers': pref.colored_sellers}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, colored_sellers=True)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'colored_sellers': pref.colored_sellers}), 200


@main_bp.route('/api/preferences/customer-sort-by', methods=['GET', 'POST'])
def customer_sort_by_preference():
    """Get or set customer sorting preference (alphabetical, grouped, or by_calls)."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        customer_sort_by = data.get('customer_sort_by', 'alphabetical')
        
        # Validate the sort option
        valid_options = ['alphabetical', 'grouped', 'by_calls']
        if customer_sort_by not in valid_options:
            return jsonify({'error': 'Invalid sort option'}), 400
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, customer_sort_by=customer_sort_by)
            db.session.add(pref)
        else:
            pref.customer_sort_by = customer_sort_by
        
        db.session.commit()
        return jsonify({'customer_sort_by': pref.customer_sort_by}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, customer_sort_by='alphabetical')
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'customer_sort_by': pref.customer_sort_by}), 200


@main_bp.route('/api/preferences/show-customers-without-calls', methods=['GET', 'POST'])
def show_customers_without_calls_preference():
    """Get or set preference for showing customers without call logs."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    if request.method == 'POST':
        data = request.get_json()
        show_customers_without_calls = data.get('show_customers_without_calls', False)
        
        # Get or create user preference
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id, show_customers_without_calls=show_customers_without_calls)
            db.session.add(pref)
        else:
            pref.show_customers_without_calls = show_customers_without_calls
        
        db.session.commit()
        return jsonify({'show_customers_without_calls': pref.show_customers_without_calls}), 200
    
    # GET request
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, show_customers_without_calls=False)
        db.session.add(pref)
        db.session.commit()
    
    return jsonify({'show_customers_without_calls': pref.show_customers_without_calls}), 200


@main_bp.route('/api/preferences/dismiss-welcome-modal', methods=['POST'])
def dismiss_welcome_modal():
    """Dismiss the first-run welcome modal."""
    user_id = g.user.id if g.user.is_authenticated else 1
    
    # Get or create user preference
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, first_run_modal_dismissed=True)
        db.session.add(pref)
    else:
        pref.first_run_modal_dismissed = True
    
    db.session.commit()
    return jsonify({'first_run_modal_dismissed': True}), 200


# =============================================================================
# Context Processor
# =============================================================================

@main_bp.app_context_processor
def inject_preferences():
    """Inject user preferences and pending link requests into all templates."""
    pref = UserPreference.query.first() if g.user.is_authenticated else None
    dark_mode = pref.dark_mode if pref else False
    customer_view_grouped = pref.customer_view_grouped if pref else False
    topic_sort_by_calls = pref.topic_sort_by_calls if pref else False
    colored_sellers = pref.colored_sellers if pref else True
    first_run_modal_dismissed = pref.first_run_modal_dismissed if pref else False
    
    # Get pending link requests count
    pending_link_requests_count = 0
    if g.user.is_authenticated and not g.user.is_stub:
        pending_link_requests_count = len(g.user.get_pending_link_requests())
    
    # Create a wrapper function that always returns color classes (CSS will handle grey state)
    def get_seller_color_with_pref(seller_id: int) -> str:
        return get_seller_color(seller_id, use_colors=True)
    
    return dict(
        dark_mode=dark_mode, 
        customer_view_grouped=customer_view_grouped, 
        topic_sort_by_calls=topic_sort_by_calls,
        colored_sellers=colored_sellers,
        first_run_modal_dismissed=first_run_modal_dismissed,
        get_seller_color=get_seller_color_with_pref,
        pending_link_requests_count=pending_link_requests_count
    )

