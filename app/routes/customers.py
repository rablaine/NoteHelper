"""
Customer routes for NoteHelper.
Handles customer listing, creation, viewing, editing, and TPID workflow.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app.models import db, Customer, Seller, Territory, CallLog, UserPreference

# Create blueprint
customers_bp = Blueprint('customers', __name__)


@customers_bp.route('/customers')
@login_required
def customers_list():
    """List all customers - alphabetical, grouped by seller, or sorted by call count based on preference."""
    user_id = current_user.id if current_user.is_authenticated else 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    
    # Determine sort method - check new field first, fall back to old grouped field for backwards compatibility
    sort_by = pref.customer_sort_by if pref else 'alphabetical'
    if sort_by == 'grouped' or (pref and pref.customer_view_grouped and sort_by == 'alphabetical'):
        sort_by = 'grouped'
    
    if sort_by == 'grouped':
        # Grouped view - get all sellers with their customers
        sellers = Seller.query.filter_by(user_id=current_user.id).options(
            db.joinedload(Seller.customers).joinedload(Customer.call_logs),
            db.joinedload(Seller.customers).joinedload(Customer.territory),
            db.joinedload(Seller.territories)
        ).order_by(Seller.name).all()
        
        # Build grouped data structure
        grouped_customers = []
        for seller in sellers:
            customers = sorted(seller.customers, key=lambda c: c.name)
            if customers:
                grouped_customers.append({
                    'seller': seller,
                    'customers': customers
                })
        
        # Get customers without a seller
        customers_without_seller = Customer.query.filter_by(user_id=current_user.id).options(
            db.joinedload(Customer.call_logs),
            db.joinedload(Customer.territory)
        ).filter_by(seller_id=None).order_by(Customer.name).all()
        
        return render_template('customers_list.html', 
                             grouped_customers=grouped_customers,
                             customers_without_seller=customers_without_seller,
                             sort_by='grouped')
    
    elif sort_by == 'by_calls':
        # Sort by number of calls (descending)
        customers = Customer.query.filter_by(user_id=current_user.id).options(
            db.joinedload(Customer.seller),
            db.joinedload(Customer.territory),
            db.joinedload(Customer.call_logs)
        ).outerjoin(CallLog).group_by(Customer.id).order_by(
            func.count(CallLog.id).desc(),
            Customer.name
        ).all()
        return render_template('customers_list.html', customers=customers, sort_by='by_calls')
    
    else:
        # Alphabetical view (default)
        customers = Customer.query.filter_by(user_id=current_user.id).options(
            db.joinedload(Customer.seller),
            db.joinedload(Customer.territory),
            db.joinedload(Customer.call_logs)
        ).order_by(Customer.name).all()
        return render_template('customers_list.html', customers=customers, sort_by='alphabetical')


@customers_bp.route('/customer/new', methods=['GET', 'POST'])
@login_required
def customer_create():
    """Create a new customer (FR003, FR031)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        nickname = request.form.get('nickname', '').strip()
        tpid = request.form.get('tpid', '').strip()
        tpid_url = request.form.get('tpid_url', '').strip()
        seller_id = request.form.get('seller_id')
        territory_id = request.form.get('territory_id')
        referrer = request.form.get('referrer', '')
        
        if not name:
            flash('Customer name is required.', 'danger')
            return redirect(url_for('customers.customer_create'))
        
        if not tpid:
            flash('TPID is required.', 'danger')
            return redirect(url_for('customers.customer_create'))
        
        try:
            tpid_value = int(tpid)
        except ValueError:
            flash('TPID must be a valid number.', 'danger')
            return redirect(url_for('customers.customer_create'))
        
        customer = Customer(
            name=name,
            nickname=nickname if nickname else None,
            tpid=tpid_value,
            tpid_url=tpid_url if tpid_url else None,
            seller_id=int(seller_id) if seller_id else None,
            territory_id=int(territory_id) if territory_id else None,
            user_id=current_user.id
        )
        db.session.add(customer)
        db.session.commit()
        
        flash(f'Customer "{name}" created successfully!', 'success')
        
        # Redirect back to referrer (FR031)
        if referrer:
            return redirect(referrer)
        
        return redirect(url_for('customers.customer_view', id=customer.id))
    
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    
    # Pre-select seller and territory from query params (FR032)
    preselect_seller_id = request.args.get('seller_id', type=int)
    preselect_territory_id = request.args.get('territory_id', type=int)
    
    # If seller is pre-selected and has exactly one territory, auto-select it
    if preselect_seller_id:
        seller = Seller.query.filter_by(user_id=current_user.id).filter_by(id=preselect_seller_id).first()
        if seller and len(seller.territories) == 1:
            preselect_territory_id = seller.territories[0].id
    
    # If territory is pre-selected and has only one seller, auto-select it (FR032)
    if preselect_territory_id and not preselect_seller_id:
        territory = Territory.query.filter_by(user_id=current_user.id).filter_by(id=preselect_territory_id).first()
        if territory:
            # territory.sellers is already a list from eager loading
            territory_sellers = territory.sellers
            if len(territory_sellers) == 1:
                preselect_seller_id = territory_sellers[0].id
    
    # Capture referrer for redirect after creation (FR031)
    referrer = request.referrer or ''
    
    return render_template('customer_form.html', 
                         customer=None, 
                         sellers=sellers, 
                         territories=territories,
                         preselect_seller_id=preselect_seller_id,
                         preselect_territory_id=preselect_territory_id,
                         referrer=referrer)


@customers_bp.route('/customer/<int:id>')
@login_required
def customer_view(id):
    """View customer details (FR008)."""
    customer = Customer.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    # Sort call logs by date (descending) - customer.call_logs is already loaded as a list
    call_logs = sorted(customer.call_logs, key=lambda c: c.call_date, reverse=True)
    return render_template('customer_view.html', customer=customer, call_logs=call_logs)


@customers_bp.route('/customer/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def customer_edit(id):
    """Edit customer (FR008)."""
    customer = Customer.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        nickname = request.form.get('nickname', '').strip()
        tpid = request.form.get('tpid', '').strip()
        tpid_url = request.form.get('tpid_url', '').strip()
        seller_id = request.form.get('seller_id')
        territory_id = request.form.get('territory_id')
        
        if not name:
            flash('Customer name is required.', 'danger')
            return redirect(url_for('customers.customer_edit', id=id))
        
        if not tpid:
            flash('TPID is required.', 'danger')
            return redirect(url_for('customers.customer_edit', id=id))
        
        try:
            tpid_value = int(tpid)
        except ValueError:
            flash('TPID must be a valid number.', 'danger')
            return redirect(url_for('customers.customer_edit', id=id))
        
        customer.name = name
        customer.nickname = nickname if nickname else None
        customer.tpid = tpid_value
        customer.tpid_url = tpid_url if tpid_url else None
        customer.seller_id = int(seller_id) if seller_id else None
        customer.territory_id = int(territory_id) if territory_id else None
        db.session.commit()
        
        flash(f'Customer "{name}" updated successfully!', 'success')
        return redirect(url_for('customers.customer_view', id=customer.id))
    
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    
    return render_template('customer_form.html', 
                         customer=customer, 
                         sellers=sellers, 
                         territories=territories,
                         referrer='')


@customers_bp.route('/tpid-workflow')
@login_required
def tpid_workflow():
    """MSX Account URL workflow page - helps fill in missing MSX Account URLs efficiently."""
    # Get all customers without MSX Account URLs, ordered by seller/territory for grouping
    customers = Customer.query.filter(
        or_(Customer.tpid_url == None, Customer.tpid_url == '')
    ).options(
        db.joinedload(Customer.seller),
        db.joinedload(Customer.territory)
    ).order_by(
        Customer.seller_id.asc(),
        Customer.territory_id.asc(),
        Customer.name.asc()
    ).all()
    
    return render_template('tpid_workflow.html', customers=customers)


@customers_bp.route('/tpid-workflow/update', methods=['POST'])
@login_required
def tpid_workflow_update():
    """Update MSX Account URLs from the workflow page."""
    try:
        # Get all form fields that start with 'tpid_url_'
        updates = {}
        for key, value in request.form.items():
            if key.startswith('tpid_url_') and value.strip():
                customer_id = int(key.replace('tpid_url_', ''))
                updates[customer_id] = value.strip()
        
        if not updates:
            flash('No MSX Account URLs to update.', 'warning')
            return redirect(url_for('customers.tpid_workflow'))
        
        # Update customers
        updated_count = 0
        for customer_id, tpid_url in updates.items():
            customer = Customer.query.get(customer_id)
            if customer:
                customer.tpid_url = tpid_url
                updated_count += 1
        
        db.session.commit()
        flash(f'Successfully updated {updated_count} MSX Account URL{"s" if updated_count != 1 else ""}.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating MSX Account URLs: {str(e)}', 'danger')
    
    return redirect(url_for('customers.tpid_workflow'))

