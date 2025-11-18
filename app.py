"""
NoteHelper - A note-taking application for Azure technical sellers.
Single-user Flask application for tracking customer call notes.
"""
import os
from datetime import datetime
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
# Database Models
# =============================================================================

# Association table for many-to-many relationship between CallLog and Topic
call_logs_topics = db.Table(
    'call_logs_topics',
    db.Column('call_log_id', db.Integer, db.ForeignKey('call_logs.id'), primary_key=True),
    db.Column('topic_id', db.Integer, db.ForeignKey('topics.id'), primary_key=True)
)


class Territory(db.Model):
    """Geographic or organizational territory for organizing customers and sellers."""
    __tablename__ = 'territories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    sellers = db.relationship('Seller', back_populates='territory', lazy='dynamic')
    customers = db.relationship('Customer', back_populates='territory', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Territory {self.name}>'


class Seller(db.Model):
    """Sales representative who can be assigned to customers and call logs."""
    __tablename__ = 'sellers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    territory = db.relationship('Territory', back_populates='sellers')
    customers = db.relationship('Customer', back_populates='seller', lazy='dynamic')
    call_logs = db.relationship('CallLog', back_populates='seller', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Seller {self.name}>'


class Customer(db.Model):
    """Customer account that can have associated call logs."""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    tpid = db.Column(db.BigInteger, nullable=False)
    tpid_url = db.Column(db.String(500), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('sellers.id'), nullable=True)
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
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
    call_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
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
        return redirect(url_for('territory_view', id=territory.id))
    
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
    week_ago = datetime.utcnow() - timedelta(days=7)
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
        territory_id = request.form.get('territory_id')
        
        if not name:
            flash('Seller name is required.', 'danger')
            return redirect(url_for('seller_create'))
        
        # Check for duplicate
        existing = Seller.query.filter_by(name=name).first()
        if existing:
            flash(f'Seller "{name}" already exists.', 'warning')
            return redirect(url_for('seller_view', id=existing.id))
        
        seller = Seller(
            name=name,
            territory_id=int(territory_id) if territory_id else None
        )
        db.session.add(seller)
        db.session.commit()
        
        flash(f'Seller "{name}" created successfully!', 'success')
        return redirect(url_for('seller_view', id=seller.id))
    
    territories = Territory.query.order_by(Territory.name).all()
    existing_sellers = Seller.query.order_by(Seller.name).all()
    return render_template('seller_form.html', seller=None, territories=territories, existing_sellers=existing_sellers)


@app.route('/seller/<int:id>')
def seller_view(id):
    """View seller details (FR007)."""
    seller = Seller.query.get_or_404(id)
    
    # Get customers with their most recent call date
    customers_data = []
    for customer in seller.customers.order_by(Customer.name).all():
        last_call = customer.get_most_recent_call_date()
        customers_data.append({
            'customer': customer,
            'last_call': last_call
        })
    
    # Sort by most recent call date (nulls last)
    customers_data.sort(key=lambda x: x['last_call'] if x['last_call'] else datetime.min, reverse=True)
    
    return render_template('seller_view.html', seller=seller, customers=customers_data)


@app.route('/seller/<int:id>/edit', methods=['GET', 'POST'])
def seller_edit(id):
    """Edit seller (FR007)."""
    seller = Seller.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_id = request.form.get('territory_id')
        
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
        seller.territory_id = int(territory_id) if territory_id else None
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
    """List all customers."""
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('customers_list.html', customers=customers)


@app.route('/customer/new', methods=['GET', 'POST'])
def customer_create():
    """Create a new customer (FR003)."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        tpid = request.form.get('tpid', '').strip()
        tpid_url = request.form.get('tpid_url', '').strip()
        seller_id = request.form.get('seller_id')
        territory_id = request.form.get('territory_id')
        
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
        return redirect(url_for('customer_view', id=customer.id))
    
    sellers = Seller.query.order_by(Seller.name).all()
    territories = Territory.query.order_by(Territory.name).all()
    return render_template('customer_form.html', customer=None, sellers=sellers, territories=territories)


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
    return render_template('customer_form.html', customer=customer, sellers=sellers, territories=territories)


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


# Placeholder routes for other sections
@app.route('/topics')
def topics_list():
    return "Topics list - Coming soon"

@app.route('/call-logs')
def call_logs_list():
    return "Call logs list - Coming soon"

@app.route('/call-log/new')
def call_log_create():
    return "Create call log - Coming soon"

@app.route('/call-log/<int:id>')
def call_log_view(id):
    return f"View call log {id} - Coming soon"


if __name__ == '__main__':
    app.run(debug=True)
