"""
Call log routes for NoteHelper.
Handles call log listing, creation, viewing, and editing.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime

from app.models import db, CallLog, Customer, Seller, Territory, Topic

# Create blueprint
call_logs_bp = Blueprint('call_logs', __name__)


@call_logs_bp.route('/call-logs')
@login_required
def call_logs_list():
    """List all call logs (FR010)."""
    call_logs = CallLog.query.filter_by(user_id=current_user.id).options(
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
    return render_template('call_logs_list.html', call_logs=call_logs)


@call_logs_bp.route('/call-log/new', methods=['GET', 'POST'])
@login_required
def call_log_create():
    """Create a new call log (FR005)."""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        referrer = request.form.get('referrer', '')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        # Parse call date
        try:
            call_date = datetime.strptime(call_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        # Get customer and auto-fill territory
        customer = Customer.query.filter_by(user_id=current_user.id).filter_by(id=int(customer_id)).first()
        territory_id = customer.territory_id if customer else None
        
        # If customer doesn't have a seller but one is selected, associate it
        if customer and not customer.seller_id and seller_id:
            customer.seller_id = int(seller_id)
            # Also update customer's territory if seller has one
            seller = Seller.query.filter_by(user_id=current_user.id).filter_by(id=int(seller_id)).first()
            if seller and seller.territory_id:
                customer.territory_id = seller.territory_id
                territory_id = seller.territory_id
        
        # Create call log
        call_log = CallLog(
            customer_id=int(customer_id),
            call_date=call_date,
            content=content,
            user_id=current_user.id
        )
        
        # Add topics
        if topic_ids:
            topics = Topic.query.filter_by(user_id=current_user.id).filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics.extend(topics)
        
        db.session.add(call_log)
        db.session.commit()
        
        flash('Call log created successfully!', 'success')
        
        # Redirect back to referrer if provided
        if referrer:
            return redirect(referrer)
        
        return redirect(url_for('call_logs.call_log_view', id=call_log.id))
    
    # GET request - load form
    # Require customer_id to be specified
    preselect_customer_id = request.args.get('customer_id', type=int)
    
    if not preselect_customer_id:
        # Redirect to customers list to select a customer first
        flash('Please select a customer before creating a call log.', 'info')
        return redirect(url_for('customers.customers_list'))
    
    # Load customer and their previous call logs
    preselect_customer = Customer.query.filter_by(user_id=current_user.id).filter_by(id=preselect_customer_id).first_or_404()
    previous_calls = CallLog.query.filter_by(user_id=current_user.id, customer_id=preselect_customer_id).options(
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
    
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    topics = Topic.query.filter_by(user_id=current_user.id).order_by(Topic.name).all()
    
    # Pre-select topic from query params
    preselect_topic_id = request.args.get('topic_id', type=int)
    
    # Capture referrer for redirect after creation
    referrer = request.referrer or ''
    
    return render_template('call_log_form.html', 
                         call_log=None, 
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         preselect_customer_id=preselect_customer_id,
                         preselect_customer=preselect_customer,
                         preselect_topic_id=preselect_topic_id,
                         previous_calls=previous_calls,
                         referrer=referrer)


@call_logs_bp.route('/call-log/<int:id>')
@login_required
def call_log_view(id):
    """View call log details (FR010)."""
    call_log = CallLog.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    return render_template('call_log_view.html', call_log=call_log)


@call_logs_bp.route('/call-log/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def call_log_edit(id):
    """Edit call log (FR010)."""
    call_log = CallLog.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        # Parse call date
        try:
            call_date = datetime.strptime(call_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        # Update call log
        call_log.customer_id = int(customer_id)
        # Seller and territory are now derived from customer
        call_log.call_date = call_date
        call_log.content = content
        
        # Update topics - remove all existing associations first
        call_log.topics = []
        if topic_ids:
            topics = Topic.query.filter_by(user_id=current_user.id).filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics = topics
        
        db.session.commit()
        
        flash('Call log updated successfully!', 'success')
        return redirect(url_for('call_logs.call_log_view', id=call_log.id))
    
    # GET request - load form
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    topics = Topic.query.filter_by(user_id=current_user.id).order_by(Topic.name).all()
    
    return render_template('call_log_form.html',
                         call_log=call_log,
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         preselect_customer_id=None,
                         preselect_topic_id=None)

