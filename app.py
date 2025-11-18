"""
NoteHelper - A note-taking application for Azure technical sellers.
Single-user Flask application for tracking customer call notes.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func, or_
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# =============================================================================
# Helper Functions
# =============================================================================

def utc_now():
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


# =============================================================================
# Database Models
# =============================================================================

# Association table for many-to-many relationship between CallLog and Topic
call_logs_topics = db.Table(
    'call_logs_topics',
    db.Column('call_log_id', db.Integer, db.ForeignKey('call_logs.id'), primary_key=True),
    db.Column('topic_id', db.Integer, db.ForeignKey('topics.id'), primary_key=True)
)

# Association table for many-to-many relationship between Seller and Territory
sellers_territories = db.Table(
    'sellers_territories',
    db.Column('seller_id', db.Integer, db.ForeignKey('sellers.id'), primary_key=True),
    db.Column('territory_id', db.Integer, db.ForeignKey('territories.id'), primary_key=True)
)


class Territory(db.Model):
    """Geographic or organizational territory for organizing customers and sellers."""
    __tablename__ = 'territories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    sellers = db.relationship(
        'Seller',
        secondary=sellers_territories,
        back_populates='territories',
        lazy='dynamic'
    )
    customers = db.relationship('Customer', back_populates='territory', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Territory {self.name}>'


class Seller(db.Model):
    """Sales representative who can be assigned to customers and call logs."""
    __tablename__ = 'sellers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # Note: territory_id column kept for backwards compatibility but will be deprecated
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    territories = db.relationship(
        'Territory',
        secondary=sellers_territories,
        back_populates='sellers',
        lazy='dynamic'
    )
    customers = db.relationship('Customer', back_populates='seller', lazy='dynamic')
    call_logs = db.relationship('CallLog', back_populates='seller', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Seller {self.name}>'


class Customer(db.Model):
    """Customer account that can be associated with call logs."""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    tpid = db.Column(db.BigInteger, nullable=False)
    tpid_url = db.Column(db.String(500), nullable=True)
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('sellers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    seller = db.relationship('Seller', back_populates='customers')
    territory = db.relationship('Territory', back_populates='customers')
    call_logs = db.relationship('CallLog', back_populates='customer', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Customer {self.name} ({self.tpid})>'
    
    def get_most_recent_call_date(self) -> Optional[datetime]:
        """Get the date of the most recent call log for this customer."""
        most_recent = self.call_logs.order_by(CallLog.call_date.desc()).first()
        return most_recent.call_date if most_recent else None
    
    def get_display_name_with_tpid(self) -> str:
        """Get customer name with TPID for display."""
        return f"{self.name} ({self.tpid})"


class Topic(db.Model):
    """Topic/technology that can be tagged on call logs."""
    __tablename__ = 'topics'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    call_logs = db.relationship(
        'CallLog',
        secondary=call_logs_topics,
        back_populates='topics',
        lazy='dynamic'
    )
    
    def __repr__(self) -> str:
        return f'<Topic {self.name}>'


class CallLog(db.Model):
    """Call log entry with rich text content and associated metadata."""
    __tablename__ = 'call_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('sellers.id'), nullable=True)
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    call_date = db.Column(db.DateTime, nullable=False, default=utc_now)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    customer = db.relationship('Customer', back_populates='call_logs')
    seller = db.relationship('Seller', back_populates='call_logs')
    topics = db.relationship(
        'Topic',
        secondary=call_logs_topics,
        back_populates='call_logs',
        lazy='dynamic'
    )
    
    def __repr__(self) -> str:
        return f'<CallLog {self.id} for {self.customer.name}>'


# =============================================================================
# Routes
# =============================================================================

@app.route('/')
def index():
    """Home page showing recent activity and stats."""
    recent_calls = CallLog.query.order_by(CallLog.call_date.desc()).limit(10).all()
    stats = {
        'call_logs': CallLog.query.count(),
        'customers': Customer.query.count(),
        'sellers': Seller.query.count(),
        'topics': Topic.query.count()
    }
    return render_template('index.html', recent_calls=recent_calls, stats=stats)


# =============================================================================
# Territory Routes (FR001, FR006)
# =============================================================================

@app.route('/territories')
def territories_list():
    """List all territories."""
    territories = Territory.query.order_by(Territory.name).all()
    return render_template('territories_list.html', territories=territories)


@app.route('/territory/new', methods=['GET', 'POST'])
def territory_create():
    """Create a new territory (FR001)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        
        if not name:
            flash('Territory name is required.', 'danger')
            return redirect(url_for('territory_create'))
        
        # Check for duplicate
        existing = Territory.query.filter_by(name=name).first()
        if existing:
            flash(f'Territory "{name}" already exists.', 'warning')
            return redirect(url_for('territory_view', id=existing.id))
        
        territory = Territory(name=name)
        db.session.add(territory)
        db.session.commit()
        
        flash(f'Territory "{name}" created successfully!', 'success')
        return redirect(url_for('territories_list'))
    
    # Show existing territories to prevent duplicates
    existing_territories = Territory.query.order_by(Territory.name).all()
    return render_template('territory_form.html', territory=None, existing_territories=existing_territories)


@app.route('/territory/<int:id>')
def territory_view(id):
    """View territory details (FR006)."""
    territory = Territory.query.get_or_404(id)
    sellers = territory.sellers.order_by(Seller.name).all()
    
    # Get calls from last 7 days
    from datetime import timedelta
    week_ago = utc_now() - timedelta(days=7)
    recent_calls = CallLog.query.filter(
        CallLog.territory_id == id,
        CallLog.call_date >= week_ago
    ).order_by(CallLog.call_date.desc()).all()
    
    return render_template('territory_view.html', 
                         territory=territory, 
                         sellers=sellers, 
                         recent_calls=recent_calls)


@app.route('/territory/<int:id>/edit', methods=['GET', 'POST'])
def territory_edit(id):
    """Edit territory (FR006)."""
    territory = Territory.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        
        if not name:
            flash('Territory name is required.', 'danger')
            return redirect(url_for('territory_edit', id=id))
        
        # Check for duplicate (excluding current territory)
        existing = Territory.query.filter(
            Territory.name == name,
            Territory.id != id
        ).first()
        if existing:
            flash(f'Territory "{name}" already exists.', 'warning')
            return redirect(url_for('territory_edit', id=id))
        
        territory.name = name
        db.session.commit()
        
        flash(f'Territory "{name}" updated successfully!', 'success')
        return redirect(url_for('territory_view', id=territory.id))
    
    existing_territories = Territory.query.filter(Territory.id != id).order_by(Territory.name).all()
    return render_template('territory_form.html', territory=territory, existing_territories=existing_territories)


# =============================================================================
# Seller Routes (FR002, FR007)
# =============================================================================

@app.route('/sellers')
def sellers_list():
    """List all sellers."""
    sellers = Seller.query.order_by(Seller.name).all()
    return render_template('sellers_list.html', sellers=sellers)


@app.route('/seller/new', methods=['GET', 'POST'])
def seller_create():
    """Create a new seller (FR002)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_ids = request.form.getlist('territory_ids')
        
        if not name:
            flash('Seller name is required.', 'danger')
            return redirect(url_for('seller_create'))
        
        # Check for duplicate
        existing = Seller.query.filter_by(name=name).first()
        if existing:
            flash(f'Seller "{name}" already exists.', 'warning')
            return redirect(url_for('seller_view', id=existing.id))
        
        seller = Seller(name=name)
        
        # Add territories to many-to-many relationship
        if territory_ids:
            for territory_id in territory_ids:
                territory = Territory.query.get(int(territory_id))
                if territory:
                    seller.territories.append(territory)
        
        db.session.add(seller)
        db.session.commit()
        
        flash(f'Seller "{name}" created successfully!', 'success')
        return redirect(url_for('sellers_list'))
    
    territories = Territory.query.order_by(Territory.name).all()
    existing_sellers = Seller.query.order_by(Seller.name).all()
    return render_template('seller_form.html', seller=None, territories=territories, existing_sellers=existing_sellers)


@app.route('/seller/<int:id>')
def seller_view(id):
    """View seller details (FR007)."""
    seller = Seller.query.get_or_404(id)
    
    # Get customers with their most recent call log
    customers_data = []
    for customer in seller.customers.order_by(Customer.name).all():
        most_recent_call = customer.call_logs.order_by(CallLog.call_date.desc()).first()
        customers_data.append({
            'customer': customer,
            'last_call': most_recent_call
        })
    
    # Sort by most recent call date (nulls last)
    # Use timezone-aware min datetime for comparison
    min_datetime = datetime.min.replace(tzinfo=timezone.utc)
    def get_sort_key(x):
        if not x['last_call']:
            return min_datetime
        call_date = x['last_call'].call_date
        # Ensure call_date is timezone-aware
        if call_date.tzinfo is None:
            call_date = call_date.replace(tzinfo=timezone.utc)
        return call_date
    customers_data.sort(key=get_sort_key, reverse=True)
    
    return render_template('seller_view.html', seller=seller, customers=customers_data)


@app.route('/seller/<int:id>/edit', methods=['GET', 'POST'])
def seller_edit(id):
    """Edit seller (FR007)."""
    seller = Seller.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_ids = request.form.getlist('territory_ids')
        
        if not name:
            flash('Seller name is required.', 'danger')
            return redirect(url_for('seller_edit', id=id))
        
        # Check for duplicate (excluding current seller)
        existing = Seller.query.filter(
            Seller.name == name,
            Seller.id != id
        ).first()
        if existing:
            flash(f'Seller "{name}" already exists.', 'warning')
            return redirect(url_for('seller_edit', id=id))
        
        seller.name = name
        
        # Update territories - clear existing and add new ones
        seller.territories.clear()
        if territory_ids:
            for territory_id in territory_ids:
                territory = Territory.query.get(int(territory_id))
                if territory:
                    seller.territories.append(territory)
        
        db.session.commit()
        
        flash(f'Seller "{name}" updated successfully!', 'success')
        return redirect(url_for('seller_view', id=seller.id))
    
    territories = Territory.query.order_by(Territory.name).all()
    existing_sellers = Seller.query.filter(Seller.id != id).order_by(Seller.name).all()
    return render_template('seller_form.html', seller=seller, territories=territories, existing_sellers=existing_sellers)


@app.route('/territory/create-inline', methods=['POST'])
def territory_create_inline():
    """Create territory inline from other forms."""
    name = request.form.get('name', '').strip()
    redirect_to = request.form.get('redirect_to', url_for('territories_list'))
    
    if name:
        existing = Territory.query.filter_by(name=name).first()
        if not existing:
            territory = Territory(name=name)
            db.session.add(territory)
            db.session.commit()
            flash(f'Territory "{name}" created successfully!', 'success')
        else:
            flash(f'Territory "{name}" already exists.', 'info')
    
    return redirect(redirect_to)


# =============================================================================
# Customer Routes (FR003, FR008)
# =============================================================================

@app.route('/customers')
def customers_list():
    """List all customers grouped by seller (FR033)."""
    # Get all sellers with their customers
    sellers = Seller.query.order_by(Seller.name).all()
    
    # Build grouped data structure
    grouped_customers = []
    for seller in sellers:
        customers = seller.customers.order_by(Customer.name).all()
        if customers:
            grouped_customers.append({
                'seller': seller,
                'customers': customers
            })
    
    # Get customers without a seller
    customers_without_seller = Customer.query.filter_by(seller_id=None).order_by(Customer.name).all()
    
    return render_template('customers_list.html', 
                         grouped_customers=grouped_customers,
                         customers_without_seller=customers_without_seller)


@app.route('/customer/new', methods=['GET', 'POST'])
def customer_create():
    """Create a new customer (FR003, FR031)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        tpid = request.form.get('tpid', '').strip()
        tpid_url = request.form.get('tpid_url', '').strip()
        seller_id = request.form.get('seller_id')
        territory_id = request.form.get('territory_id')
        referrer = request.form.get('referrer', '')
        
        if not name:
            flash('Customer name is required.', 'danger')
            return redirect(url_for('customer_create'))
        
        if not tpid:
            flash('TPID is required.', 'danger')
            return redirect(url_for('customer_create'))
        
        try:
            tpid_value = int(tpid)
        except ValueError:
            flash('TPID must be a valid number.', 'danger')
            return redirect(url_for('customer_create'))
        
        customer = Customer(
            name=name,
            tpid=tpid_value,
            tpid_url=tpid_url if tpid_url else None,
            seller_id=int(seller_id) if seller_id else None,
            territory_id=int(territory_id) if territory_id else None
        )
        db.session.add(customer)
        db.session.commit()
        
        flash(f'Customer "{name}" created successfully!', 'success')
        
        # Redirect back to referrer (FR031)
        if referrer:
            return redirect(referrer)
        
        return redirect(url_for('customer_view', id=customer.id))
    
    sellers = Seller.query.order_by(Seller.name).all()
    territories = Territory.query.order_by(Territory.name).all()
    
    # Build seller customers map for duplicate prevention (FR030)
    seller_customers = {}
    for seller in sellers:
        customers = seller.customers.order_by(Customer.name).all()
        seller_customers[seller.id] = [
            {'id': c.id, 'name': c.name, 'tpid': c.tpid} 
            for c in customers
        ]
    
    # Pre-select seller and territory from query params (FR032)
    preselect_seller_id = request.args.get('seller_id', type=int)
    preselect_territory_id = request.args.get('territory_id', type=int)
    
    # If seller is pre-selected and has exactly one territory, auto-select it
    if preselect_seller_id:
        seller = Seller.query.get(preselect_seller_id)
        if seller and seller.territories.count() == 1:
            preselect_territory_id = seller.territories.first().id
    
    # If territory is pre-selected and has only one seller, auto-select it (FR032)
    if preselect_territory_id and not preselect_seller_id:
        territory = Territory.query.get(preselect_territory_id)
        if territory:
            territory_sellers = territory.sellers.all()
            if len(territory_sellers) == 1:
                preselect_seller_id = territory_sellers[0].id
    
    # Capture referrer for redirect after creation (FR031)
    referrer = request.referrer or ''
    
    return render_template('customer_form.html', 
                         customer=None, 
                         sellers=sellers, 
                         territories=territories,
                         seller_customers=seller_customers,
                         preselect_seller_id=preselect_seller_id,
                         preselect_territory_id=preselect_territory_id,
                         referrer=referrer)


@app.route('/customer/<int:id>')
def customer_view(id):
    """View customer details (FR008)."""
    customer = Customer.query.get_or_404(id)
    call_logs = customer.call_logs.order_by(CallLog.call_date.desc()).all()
    return render_template('customer_view.html', customer=customer, call_logs=call_logs)


@app.route('/customer/<int:id>/edit', methods=['GET', 'POST'])
def customer_edit(id):
    """Edit customer (FR008)."""
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        tpid = request.form.get('tpid', '').strip()
        tpid_url = request.form.get('tpid_url', '').strip()
        seller_id = request.form.get('seller_id')
        territory_id = request.form.get('territory_id')
        
        if not name:
            flash('Customer name is required.', 'danger')
            return redirect(url_for('customer_edit', id=id))
        
        if not tpid:
            flash('TPID is required.', 'danger')
            return redirect(url_for('customer_edit', id=id))
        
        try:
            tpid_value = int(tpid)
        except ValueError:
            flash('TPID must be a valid number.', 'danger')
            return redirect(url_for('customer_edit', id=id))
        
        customer.name = name
        customer.tpid = tpid_value
        customer.tpid_url = tpid_url if tpid_url else None
        customer.seller_id = int(seller_id) if seller_id else None
        customer.territory_id = int(territory_id) if territory_id else None
        db.session.commit()
        
        flash(f'Customer "{name}" updated successfully!', 'success')
        return redirect(url_for('customer_view', id=customer.id))
    
    sellers = Seller.query.order_by(Seller.name).all()
    territories = Territory.query.order_by(Territory.name).all()
    
    # Build seller customers map for duplicate prevention (FR030)
    seller_customers = {}
    for seller in sellers:
        customers = seller.customers.order_by(Customer.name).all()
        seller_customers[seller.id] = [
            {'id': c.id, 'name': c.name, 'tpid': c.tpid} 
            for c in customers
        ]
    
    return render_template('customer_form.html', 
                         customer=customer, 
                         sellers=sellers, 
                         territories=territories,
                         seller_customers=seller_customers,
                         referrer='')


@app.route('/seller/create-inline', methods=['POST'])
def seller_create_inline():
    """Create seller inline from other forms."""
    name = request.form.get('name', '').strip()
    redirect_to = request.form.get('redirect_to', url_for('sellers_list'))
    
    if name:
        existing = Seller.query.filter_by(name=name).first()
        if not existing:
            seller = Seller(name=name)
            db.session.add(seller)
            db.session.commit()
            flash(f'Seller "{name}" created successfully!', 'success')
        else:
            flash(f'Seller "{name}" already exists.', 'info')
    
    return redirect(redirect_to)


# ============================================================================
# TOPIC ROUTES (FR004, FR009)
# ============================================================================

@app.route('/topics')
def topics_list():
    """List all topics (FR009)."""
    topics = Topic.query.order_by(Topic.name).all()
    return render_template('topics_list.html', topics=topics)


@app.route('/api/topic/create', methods=['POST'])
def api_topic_create():
    """API endpoint to create a new topic via AJAX (FR027)."""
    data = request.get_json()
    name = data.get('name', '').strip() if data else ''
    
    if not name:
        return jsonify({'error': 'Topic name is required'}), 400
    
    # Check for duplicate topic names (case-insensitive)
    existing = Topic.query.filter(func.lower(Topic.name) == func.lower(name)).first()
    if existing:
        return jsonify({
            'id': existing.id,
            'name': existing.name,
            'description': existing.description or '',
            'existed': True
        }), 200
    
    # Create new topic
    topic = Topic(name=name, description=None)
    db.session.add(topic)
    db.session.commit()
    
    return jsonify({
        'id': topic.id,
        'name': topic.name,
        'description': topic.description or '',
        'existed': False
    }), 201


@app.route('/topic/new', methods=['GET', 'POST'])
def topic_create():
    """Create a new topic (FR004)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash('Topic name is required.', 'danger')
            return redirect(url_for('topic_create'))
        
        # Check for duplicate topic names
        existing = Topic.query.filter_by(name=name).first()
        if existing:
            flash(f'Topic "{name}" already exists.', 'warning')
            return redirect(url_for('topic_view', id=existing.id))
        
        topic = Topic(
            name=name,
            description=description if description else None
        )
        db.session.add(topic)
        db.session.commit()
        
        flash(f'Topic "{name}" created successfully!', 'success')
        return redirect(url_for('topics_list'))
    
    return render_template('topic_form.html', topic=None)


@app.route('/topic/<int:id>')
def topic_view(id):
    """View topic details (FR009)."""
    topic = Topic.query.get_or_404(id)
    call_logs = topic.call_logs.order_by(CallLog.call_date.desc()).all()
    return render_template('topic_view.html', topic=topic, call_logs=call_logs)


@app.route('/topic/<int:id>/edit', methods=['GET', 'POST'])
def topic_edit(id):
    """Edit topic (FR009)."""
    topic = Topic.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash('Topic name is required.', 'danger')
            return redirect(url_for('topic_edit', id=id))
        
        # Check for duplicate topic names (excluding current topic)
        existing = Topic.query.filter(Topic.name == name, Topic.id != id).first()
        if existing:
            flash(f'Topic "{name}" already exists.', 'warning')
            return redirect(url_for('topic_edit', id=id))
        
        topic.name = name
        topic.description = description if description else None
        db.session.commit()
        
        flash(f'Topic "{name}" updated successfully!', 'success')
        return redirect(url_for('topic_view', id=topic.id))
    
    return render_template('topic_form.html', topic=topic)


# ============================================================================
# CALL LOG ROUTES (FR005, FR010)
# ============================================================================

@app.route('/call-logs')
def call_logs_list():
    """List all call logs (FR010)."""
    call_logs = CallLog.query.order_by(CallLog.call_date.desc()).all()
    return render_template('call_logs_list.html', call_logs=call_logs)


@app.route('/call-log/new', methods=['GET', 'POST'])
def call_log_create():
    """Create a new call log (FR005)."""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_log_create'))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_log_create'))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_log_create'))
        
        # Parse call date
        try:
            call_date = datetime.strptime(call_date_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('call_log_create'))
        
        # Get customer and auto-fill territory
        customer = Customer.query.get(int(customer_id))
        territory_id = customer.territory_id if customer else None
        
        # If customer doesn't have a seller but one is selected, associate it
        if customer and not customer.seller_id and seller_id:
            customer.seller_id = int(seller_id)
            # Also update customer's territory if seller has one
            seller = Seller.query.get(int(seller_id))
            if seller and seller.territory_id:
                customer.territory_id = seller.territory_id
                territory_id = seller.territory_id
        
        # Create call log
        call_log = CallLog(
            customer_id=int(customer_id),
            seller_id=int(seller_id) if seller_id else None,
            territory_id=territory_id,
            call_date=call_date,
            content=content
        )
        
        # Add topics
        if topic_ids:
            topics = Topic.query.filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics.extend(topics)
        
        db.session.add(call_log)
        db.session.commit()
        
        flash('Call log created successfully!', 'success')
        return redirect(url_for('call_log_view', id=call_log.id))
    
    # GET request - load form
    customers = Customer.query.order_by(Customer.name).all()
    sellers = Seller.query.order_by(Seller.name).all()
    topics = Topic.query.order_by(Topic.name).all()
    
    # Pre-select customer/topic from query params
    preselect_customer_id = request.args.get('customer_id', type=int)
    preselect_topic_id = request.args.get('topic_id', type=int)
    
    # Pre-select seller if customer is pre-selected and has a seller
    preselect_seller_id = None
    if preselect_customer_id:
        customer = Customer.query.get(preselect_customer_id)
        if customer and customer.seller_id:
            preselect_seller_id = customer.seller_id
    
    return render_template('call_log_form.html', 
                         call_log=None, 
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         preselect_customer_id=preselect_customer_id,
                         preselect_seller_id=preselect_seller_id,
                         preselect_topic_id=preselect_topic_id)


@app.route('/call-log/<int:id>')
def call_log_view(id):
    """View call log details (FR010)."""
    call_log = CallLog.query.get_or_404(id)
    return render_template('call_log_view.html', call_log=call_log)


@app.route('/call-log/<int:id>/edit', methods=['GET', 'POST'])
def call_log_edit(id):
    """Edit call log (FR010)."""
    call_log = CallLog.query.get_or_404(id)
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_log_edit', id=id))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_log_edit', id=id))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_log_edit', id=id))
        
        # Parse call date
        try:
            call_date = datetime.strptime(call_date_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('call_log_edit', id=id))
        
        # Get customer and update territory
        customer = Customer.query.get(int(customer_id))
        territory_id = customer.territory_id if customer else None
        
        # Update call log
        call_log.customer_id = int(customer_id)
        call_log.seller_id = int(seller_id) if seller_id else None
        call_log.territory_id = territory_id
        call_log.call_date = call_date
        call_log.content = content
        
        # Update topics - remove all existing associations first
        call_log.topics = []
        if topic_ids:
            topics = Topic.query.filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics = topics
        
        db.session.commit()
        
        flash('Call log updated successfully!', 'success')
        return redirect(url_for('call_log_view', id=call_log.id))
    
    # GET request - load form
    customers = Customer.query.order_by(Customer.name).all()
    sellers = Seller.query.order_by(Seller.name).all()
    topics = Topic.query.order_by(Topic.name).all()
    
    return render_template('call_log_form.html',
                         call_log=call_log,
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         preselect_customer_id=None,
                         preselect_topic_id=None)


# ============================================================================
# SEARCH AND FILTER ROUTES (FR011)
# ============================================================================

@app.route('/search')
def search():
    """Search and filter call logs (FR011)."""
    # Get filter parameters
    search_text = request.args.get('q', '').strip()
    customer_id = request.args.get('customer_id', type=int)
    seller_id = request.args.get('seller_id', type=int)
    territory_id = request.args.get('territory_id', type=int)
    topic_ids = request.args.getlist('topic_ids', type=int)
    
    # Start with base query
    query = CallLog.query
    
    # Apply filters
    if search_text:
        query = query.filter(CallLog.content.ilike(f'%{search_text}%'))
    
    if customer_id:
        query = query.filter(CallLog.customer_id == customer_id)
    
    if seller_id:
        query = query.filter(CallLog.seller_id == seller_id)
    
    if territory_id:
        query = query.filter(CallLog.territory_id == territory_id)
    
    if topic_ids:
        # Filter by topics (call logs that have ANY of the selected topics)
        query = query.join(CallLog.topics).filter(Topic.id.in_(topic_ids))
    
    # Get filtered call logs
    call_logs = query.order_by(CallLog.call_date.desc()).all()
    
    # Group call logs by Seller → Customer structure (FR011)
    # Structure: { seller_id: { 'seller': Seller, 'customers': { customer_id: { 'customer': Customer, 'calls': [CallLog] } } } }
    grouped_data = {}
    
    for call in call_logs:
        seller_id_key = call.seller_id if call.seller_id else 0  # 0 = no seller
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


if __name__ == '__main__':
    app.run(debug=True)
