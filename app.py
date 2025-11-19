"""
NoteHelper - A note-taking application for Azure technical sellers.
Single-user Flask application for tracking customer call notes.
"""
import os
from datetime import datetime, timezone, date
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

# PostgreSQL connection pool settings to handle idle connections
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,  # Verify connections before using them
    'pool_recycle': 300,    # Recycle connections after 5 minutes
    'pool_size': 10,        # Connection pool size
    'max_overflow': 5       # Max overflow connections
}

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# SAFETY CHECK: Ensure we have a valid database URL
if not app.config.get('SQLALCHEMY_DATABASE_URI'):
    raise RuntimeError(
        "CRITICAL: No DATABASE_URL configured!\n"
        "Check your .env file or environment variables."
    )

# SAFETY CHECK: Prevent accidental test database usage in production
if not os.getenv('TESTING') and 'sqlite' in str(app.config.get('SQLALCHEMY_DATABASE_URI', '')).lower():
    raise RuntimeError(
        "CRITICAL: Attempting to run production app with SQLite database!\n"
        "This usually means DATABASE_URL environment variable was not loaded correctly.\n"
        "Check your .env file and ensure DATABASE_URL points to PostgreSQL."
    )


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

# Association table for many-to-many relationship between Customer and Vertical
customers_verticals = db.Table(
    'customers_verticals',
    db.Column('customer_id', db.Integer, db.ForeignKey('customers.id'), primary_key=True),
    db.Column('vertical_id', db.Integer, db.ForeignKey('verticals.id'), primary_key=True)
)

# Association table for many-to-many relationship between SolutionEngineer and POD
solution_engineers_pods = db.Table(
    'solution_engineers_pods',
    db.Column('solution_engineer_id', db.Integer, db.ForeignKey('solution_engineers.id'), primary_key=True),
    db.Column('pod_id', db.Integer, db.ForeignKey('pods.id'), primary_key=True)
)


class POD(db.Model):
    """POD (Practice Operating Division) - organizational grouping of territories and personnel."""
    __tablename__ = 'pods'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    territories = db.relationship('Territory', back_populates='pod', lazy='select')
    solution_engineers = db.relationship(
        'SolutionEngineer',
        secondary=solution_engineers_pods,
        back_populates='pods',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        return f'<POD {self.name}>'


class SolutionEngineer(db.Model):
    """Solution Engineer (Azure Technical Seller) assigned to a POD with a specific specialty."""
    __tablename__ = 'solution_engineers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    alias = db.Column(db.String(100), nullable=True)  # Microsoft email alias
    specialty = db.Column(db.String(50), nullable=True)  # Azure Data, Azure Core and Infra, Azure Apps and AI
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    pods = db.relationship(
        'POD',
        secondary=solution_engineers_pods,
        back_populates='solution_engineers',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        return f'<SolutionEngineer {self.name} ({self.specialty})>'
    
    def get_email(self) -> Optional[str]:
        """Get email address from alias."""
        if self.alias:
            return f"{self.alias}@microsoft.com"
        return None


class Vertical(db.Model):
    """Industry vertical and category for customer classification."""
    __tablename__ = 'verticals'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)  # e.g., "Financial Services"
    category = db.Column(db.String(200), nullable=True)  # e.g., "Banking"
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    customers = db.relationship(
        'Customer',
        secondary=customers_verticals,
        back_populates='verticals',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        if self.category:
            return f'<Vertical {self.name} - {self.category}>'
        return f'<Vertical {self.name}>'


class Territory(db.Model):
    """Geographic or organizational territory for organizing customers and sellers."""
    __tablename__ = 'territories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    pod_id = db.Column(db.Integer, db.ForeignKey('pods.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    pod = db.relationship('POD', back_populates='territories')
    sellers = db.relationship(
        'Seller',
        secondary=sellers_territories,
        back_populates='territories',
        lazy='select'
    )
    customers = db.relationship('Customer', back_populates='territory', lazy='select')
    
    def __repr__(self) -> str:
        return f'<Territory {self.name}>'


class Seller(db.Model):
    """Sales representative who can be assigned to customers and call logs."""
    __tablename__ = 'sellers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    alias = db.Column(db.String(100), nullable=True)  # Microsoft email alias
    seller_type = db.Column(db.String(20), nullable=False, default='Growth')  # Acquisition or Growth
    # Note: territory_id column kept for backwards compatibility but will be deprecated
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    territories = db.relationship(
        'Territory',
        secondary=sellers_territories,
        back_populates='sellers',
        lazy='select'
    )
    customers = db.relationship('Customer', back_populates='seller', lazy='select')
    call_logs = db.relationship('CallLog', back_populates='seller', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f'<Seller {self.name} ({self.seller_type})>'
    
    def get_email(self) -> Optional[str]:
        """Get email address from alias."""
        if self.alias:
            return f"{self.alias}@microsoft.com"
        return None


class Customer(db.Model):
    """Customer account that can be associated with call logs."""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    nickname = db.Column(db.String(200), nullable=True)
    tpid = db.Column(db.BigInteger, nullable=False)
    tpid_url = db.Column(db.String(500), nullable=True)
    territory_id = db.Column(db.Integer, db.ForeignKey('territories.id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('sellers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    seller = db.relationship('Seller', back_populates='customers')
    territory = db.relationship('Territory', back_populates='customers')
    call_logs = db.relationship('CallLog', back_populates='customer', lazy='select')
    verticals = db.relationship(
        'Vertical',
        secondary=customers_verticals,
        back_populates='customers',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        return f'<Customer {self.name} ({self.tpid})>'
    
    def get_most_recent_call_date(self) -> Optional[datetime]:
        """Get the date of the most recent call log for this customer."""
        if not self.call_logs:
            return None
        most_recent = max(self.call_logs, key=lambda x: x.call_date)
        return most_recent.call_date
    
    def get_display_name_with_tpid(self) -> str:
        """Get customer name with TPID for display."""
        return f"{self.name} ({self.tpid})"
    
    def get_display_name(self) -> str:
        """Get customer name for display, using nickname if available."""
        return self.nickname if self.nickname else self.name
    
    def get_account_type(self) -> str:
        """Get account type (Acquisition/Growth) from assigned seller."""
        if self.seller:
            return self.seller.seller_type
        return "Unknown"


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
        lazy='select'
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
    call_date = db.Column(db.Date, nullable=False, default=lambda: date.today())
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    customer = db.relationship('Customer', back_populates='call_logs')
    seller = db.relationship('Seller', back_populates='call_logs')
    territory = db.relationship('Territory')
    topics = db.relationship(
        'Topic',
        secondary=call_logs_topics,
        back_populates='call_logs',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        return f'<CallLog {self.id} for {self.customer.name}>'


class UserPreference(db.Model):
    """User preferences including dark mode and customer view settings."""
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, default=1)  # Single user system
    dark_mode = db.Column(db.Boolean, default=False, nullable=False)
    customer_view_grouped = db.Column(db.Boolean, default=False, nullable=False)
    topic_sort_by_calls = db.Column(db.Boolean, default=False, nullable=False)
    territory_view_accounts = db.Column(db.Boolean, default=False, nullable=False)  # False = recent calls, True = accounts
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    def __repr__(self) -> str:
        return f'<UserPreference user_id={self.user_id} dark_mode={self.dark_mode} customer_view_grouped={self.customer_view_grouped} topic_sort_by_calls={self.topic_sort_by_calls} territory_view_accounts={self.territory_view_accounts}>'


# =============================================================================
# Routes
# =============================================================================

@app.route('/')
def index():
    """Home page showing recent activity and stats."""
    # Eager load relationships for recent calls to avoid N+1 queries
    recent_calls = CallLog.query.options(
        db.joinedload(CallLog.customer),
        db.joinedload(CallLog.seller),
        db.joinedload(CallLog.territory)
    ).order_by(CallLog.call_date.desc()).limit(10).all()
    
    # Count queries are fast on these small tables
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
    territories = Territory.query.options(
        db.joinedload(Territory.sellers),
        db.joinedload(Territory.customers),
        db.joinedload(Territory.pod)
    ).order_by(Territory.name).all()
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
    territory = Territory.query.options(
        db.joinedload(Territory.pod)
    ).get_or_404(id)
    # Sort sellers in-memory since they're eager-loaded
    sellers = sorted(territory.sellers, key=lambda s: s.name)
    
    # Get user preference for territory view
    user_id = 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    show_accounts = pref.territory_view_accounts if pref else False
    
    recent_calls = []
    growth_customers = []
    acquisition_customers = []
    
    if show_accounts:
        # Get all customers in this territory with call counts
        from sqlalchemy import func
        customers_with_counts = db.session.query(
            Customer,
            func.count(CallLog.id).label('call_count')
        ).join(
            Seller, Customer.seller_id == Seller.id
        ).filter(
            Seller.territories.any(Territory.id == id)
        ).outerjoin(
            CallLog, Customer.id == CallLog.customer_id
        ).group_by(Customer.id, Seller.id, Seller.seller_type).all()
        
        # Group by seller type and sort by call count
        for customer, call_count in customers_with_counts:
            customer.call_count = call_count  # Attach count for template
            # Determine customer type by their seller
            if customer.seller:
                if customer.seller.seller_type == 'Growth':
                    growth_customers.append(customer)
                elif customer.seller.seller_type == 'Acquisition':
                    acquisition_customers.append(customer)
        
        # Sort by call count descending
        growth_customers.sort(key=lambda c: c.call_count, reverse=True)
        acquisition_customers.sort(key=lambda c: c.call_count, reverse=True)
    else:
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
                         recent_calls=recent_calls,
                         show_accounts=show_accounts,
                         growth_customers=growth_customers,
                         acquisition_customers=acquisition_customers)


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
# POD Routes
# =============================================================================

@app.route('/pods')
def pods_list():
    """List all PODs."""
    pods = POD.query.options(
        db.joinedload(POD.territories),
        db.joinedload(POD.solution_engineers)
    ).order_by(POD.name).all()
    return render_template('pods_list.html', pods=pods)


@app.route('/pod/<int:id>')
def pod_view(id):
    """View POD details with territories, sellers, and solution engineers."""
    # Use selectinload for better performance with collections
    pod = POD.query.options(
        db.selectinload(POD.territories).selectinload(Territory.sellers),
        db.selectinload(POD.solution_engineers)
    ).get_or_404(id)
    
    # Get all sellers from all territories in this POD
    sellers = set()
    for territory in pod.territories:
        for seller in territory.sellers:
            sellers.add(seller)
    sellers = sorted(list(sellers), key=lambda s: s.name)
    
    # Sort territories and solution engineers
    territories = sorted(pod.territories, key=lambda t: t.name)
    solution_engineers = sorted(pod.solution_engineers, key=lambda se: se.name)
    
    return render_template('pod_view.html',
                         pod=pod,
                         territories=territories,
                         sellers=sellers,
                         solution_engineers=solution_engineers)


@app.route('/pod/<int:id>/edit', methods=['GET', 'POST'])
def pod_edit(id):
    """Edit POD with territories, sellers, and solution engineers."""
    pod = POD.query.options(
        db.selectinload(POD.territories),
        db.selectinload(POD.solution_engineers)
    ).get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_ids = request.form.getlist('territory_ids')
        se_ids = request.form.getlist('se_ids')
        
        if not name:
            flash('POD name is required.', 'danger')
            return redirect(url_for('pod_edit', id=id))
        
        # Check for duplicate
        existing = POD.query.filter(POD.name == name, POD.id != id).first()
        if existing:
            flash(f'POD "{name}" already exists.', 'warning')
            return redirect(url_for('pod_view', id=existing.id))
        
        pod.name = name
        
        # Update territories
        pod.territories.clear()
        for territory_id in territory_ids:
            territory = Territory.query.get(int(territory_id))
            if territory:
                pod.territories.append(territory)
        
        # Update solution engineers
        pod.solution_engineers.clear()
        for se_id in se_ids:
            se = SolutionEngineer.query.get(int(se_id))
            if se:
                pod.solution_engineers.append(se)
        
        db.session.commit()
        
        flash(f'POD "{name}" updated successfully!', 'success')
        return redirect(url_for('pod_view', id=pod.id))
    
    # Get all territories and solution engineers for the form
    all_territories = Territory.query.options(
        db.selectinload(Territory.sellers)
    ).order_by(Territory.name).all()
    all_ses = SolutionEngineer.query.order_by(SolutionEngineer.name).all()
    
    return render_template('pod_form.html', pod=pod, all_territories=all_territories, all_ses=all_ses)


# =============================================================================
# Solution Engineer Routes
# =============================================================================

@app.route('/solution-engineers')
def solution_engineers_list():
    """List all solution engineers."""
    ses = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).order_by(SolutionEngineer.name).all()
    return render_template('solution_engineers_list.html', solution_engineers=ses)


@app.route('/solution-engineer/<int:id>')
def solution_engineer_view(id):
    """View solution engineer details."""
    se = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).get_or_404(id)
    
    # Sort PODs
    pods = sorted(se.pods, key=lambda p: p.name)
    
    return render_template('solution_engineer_view.html',
                         solution_engineer=se,
                         pods=pods)


@app.route('/solution-engineer/<int:id>/edit', methods=['GET', 'POST'])
def solution_engineer_edit(id):
    """Edit solution engineer details."""
    se = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        alias = request.form.get('alias', '').strip()
        specialty = request.form.get('specialty', '').strip()
        pod_ids = request.form.getlist('pod_ids')
        
        if not name:
            flash('Solution Engineer name is required.', 'danger')
            return redirect(url_for('solution_engineer_edit', id=id))
        
        se.name = name
        se.alias = alias if alias else None
        se.specialty = specialty if specialty else None
        
        # Update POD associations
        se.pods.clear()
        for pod_id in pod_ids:
            pod = POD.query.get(int(pod_id))
            if pod:
                se.pods.append(pod)
        
        db.session.commit()
        
        flash(f'Solution Engineer "{name}" updated successfully!', 'success')
        return redirect(url_for('solution_engineer_view', id=se.id))
    
    # Get all PODs for the form
    all_pods = POD.query.order_by(POD.name).all()
    return render_template('solution_engineer_form.html', solution_engineer=se, all_pods=all_pods)


# =============================================================================
# Seller Routes (FR002, FR007)
# =============================================================================

@app.route('/sellers')
def sellers_list():
    """List all sellers."""
    sellers = Seller.query.options(
        db.joinedload(Seller.territories).joinedload(Territory.pod),
        db.joinedload(Seller.customers)
    ).order_by(Seller.name).all()
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
    for customer in sorted(seller.customers, key=lambda c: c.name):
        # Get most recent call log (sort in-memory since already loaded)
        sorted_calls = sorted(customer.call_logs, key=lambda c: c.call_date, reverse=True)
        most_recent_call = sorted_calls[0] if sorted_calls else None
        customers_data.append({
            'customer': customer,
            'last_call': most_recent_call
        })
    
    # Sort by most recent call date (nulls last)
    min_date = date.min
    def get_sort_key(x):
        if not x['last_call']:
            return min_date
        return x['last_call'].call_date
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
        
        # Update territories - replace the collection
        seller.territories = []
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
    """List all customers - alphabetical or grouped by seller based on preference."""
    user_id = 1  # Single user system
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    
    if pref and pref.customer_view_grouped:
        # Grouped view - get all sellers with their customers
        sellers = Seller.query.options(
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
        customers_without_seller = Customer.query.options(
            db.joinedload(Customer.call_logs),
            db.joinedload(Customer.territory)
        ).filter_by(seller_id=None).order_by(Customer.name).all()
        
        return render_template('customers_list.html', 
                             grouped_customers=grouped_customers,
                             customers_without_seller=customers_without_seller,
                             is_grouped=True)
    else:
        # Alphabetical view
        customers = Customer.query.options(
            db.joinedload(Customer.seller),
            db.joinedload(Customer.territory),
            db.joinedload(Customer.call_logs)
        ).order_by(Customer.name).all()
        return render_template('customers_list.html', customers=customers, is_grouped=False)


@app.route('/customer/new', methods=['GET', 'POST'])
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
            nickname=nickname if nickname else None,
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
    
    # Pre-select seller and territory from query params (FR032)
    preselect_seller_id = request.args.get('seller_id', type=int)
    preselect_territory_id = request.args.get('territory_id', type=int)
    
    # If seller is pre-selected and has exactly one territory, auto-select it
    if preselect_seller_id:
        seller = Seller.query.get(preselect_seller_id)
        if seller and len(seller.territories) == 1:
            preselect_territory_id = seller.territories[0].id
    
    # If territory is pre-selected and has only one seller, auto-select it (FR032)
    if preselect_territory_id and not preselect_seller_id:
        territory = Territory.query.get(preselect_territory_id)
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


@app.route('/customer/<int:id>')
def customer_view(id):
    """View customer details (FR008)."""
    customer = Customer.query.get_or_404(id)
    # Sort call logs by date (descending) - customer.call_logs is already loaded as a list
    call_logs = sorted(customer.call_logs, key=lambda c: c.call_date, reverse=True)
    return render_template('customer_view.html', customer=customer, call_logs=call_logs)


@app.route('/customer/<int:id>/edit', methods=['GET', 'POST'])
def customer_edit(id):
    """Edit customer (FR008)."""
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        nickname = request.form.get('nickname', '').strip()
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
        customer.nickname = nickname if nickname else None
        customer.tpid = tpid_value
        customer.tpid_url = tpid_url if tpid_url else None
        customer.seller_id = int(seller_id) if seller_id else None
        customer.territory_id = int(territory_id) if territory_id else None
        db.session.commit()
        
        flash(f'Customer "{name}" updated successfully!', 'success')
        return redirect(url_for('customer_view', id=customer.id))
    
    sellers = Seller.query.order_by(Seller.name).all()
    territories = Territory.query.order_by(Territory.name).all()
    
    return render_template('customer_form.html', 
                         customer=customer, 
                         sellers=sellers, 
                         territories=territories,
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
    user_id = 1  # Single user system
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    
    # Load topics with eager loading
    topics = Topic.query.options(db.joinedload(Topic.call_logs)).all()
    
    # Sort based on preference
    if pref and pref.topic_sort_by_calls:
        # Sort by number of calls (descending), then by name
        topics = sorted(topics, key=lambda t: (-len(t.call_logs), t.name.lower()))
    else:
        # Sort alphabetically
        topics = sorted(topics, key=lambda t: t.name.lower())
    
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
    # Sort call logs in-memory since they're eager-loaded
    call_logs = sorted(topic.call_logs, key=lambda c: c.call_date, reverse=True)
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


@app.route('/topic/<int:id>/delete', methods=['POST'])
def topic_delete(id):
    """Delete topic and remove from all associated call logs."""
    topic = Topic.query.get_or_404(id)
    topic_name = topic.name
    
    # Get all call logs associated with this topic
    call_logs_count = topic.call_logs.count()
    
    # Delete the topic (SQLAlchemy will automatically remove associations from call_logs_topics table)
    db.session.delete(topic)
    db.session.commit()
    
    if call_logs_count > 0:
        flash(f'Topic "{topic_name}" deleted and removed from {call_logs_count} call log(s).', 'success')
    else:
        flash(f'Topic "{topic_name}" deleted successfully.', 'success')
    
    return redirect(url_for('topics_list'))


# ============================================================================
# CALL LOG ROUTES (FR005, FR010)
# ============================================================================

@app.route('/call-logs')
def call_logs_list():
    """List all call logs (FR010)."""
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer),
        db.joinedload(CallLog.seller),
        db.joinedload(CallLog.territory),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
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
        referrer = request.form.get('referrer', '')
        
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
            call_date = datetime.strptime(call_date_str, '%Y-%m-%d').date()
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
        
        # Redirect back to referrer if provided
        if referrer:
            return redirect(referrer)
        
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
    
    # Capture referrer for redirect after creation
    referrer = request.referrer or ''
    
    return render_template('call_log_form.html', 
                         call_log=None, 
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         preselect_customer_id=preselect_customer_id,
                         preselect_seller_id=preselect_seller_id,
                         preselect_topic_id=preselect_topic_id,
                         referrer=referrer)


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
            call_date = datetime.strptime(call_date_str, '%Y-%m-%d').date()
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


@app.route('/preferences')
def preferences():
    """User preferences page."""
    user_id = 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.session.add(pref)
        db.session.commit()
    
    return render_template('preferences.html', 
                         dark_mode=pref.dark_mode,
                         customer_view_grouped=pref.customer_view_grouped,
                         topic_sort_by_calls=pref.topic_sort_by_calls,
                         territory_view_accounts=pref.territory_view_accounts)


@app.route('/data-management')
def data_management():
    """Data import/export management page."""
    return render_template('data_management.html')


@app.route('/api/data-management/stats', methods=['GET'])
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


@app.route('/api/data-management/clear', methods=['POST'])
def data_management_clear():
    """Clear all data from the database."""
    try:
        # Delete in correct order to handle foreign key constraints
        # Delete call logs first (depends on customers and topics)
        CallLog.query.delete()
        
        # Delete customer-vertical associations
        db.session.execute(customers_verticals.delete())
        
        # Delete customers
        Customer.query.delete()
        
        # Delete solution engineers (depends on PODs)
        SolutionEngineer.query.delete()
        
        # Delete verticals
        Vertical.query.delete()
        
        # Delete topics
        Topic.query.delete()
        
        # Delete seller-territory associations
        db.session.execute(sellers_territories.delete())
        
        # Delete sellers and territories (territories depend on PODs)
        Seller.query.delete()
        Territory.query.delete()
        
        # Delete PODs
        POD.query.delete()
        
        db.session.commit()
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/data-management/export/json', methods=['GET'])
def export_full_json():
    """Export complete database as JSON for disaster recovery."""
    import json
    from datetime import datetime
    
    data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'version': '1.0',
        'pods': [{'id': p.id, 'name': p.name} for p in POD.query.all()],
        'territories': [{'id': t.id, 'name': t.name, 'pod_id': t.pod_id} for t in Territory.query.all()],
        'sellers': [{'id': s.id, 'name': s.name, 'alias': s.alias, 'seller_type': s.seller_type, 
                     'territory_ids': [t.id for t in s.territories]} for s in Seller.query.all()],
        'solution_engineers': [{'id': se.id, 'name': se.name, 'alias': se.alias, 'specialty': se.specialty,
                               'pod_ids': [p.id for p in se.pods]} for se in SolutionEngineer.query.all()],
        'verticals': [{'id': v.id, 'name': v.name} for v in Vertical.query.all()],
        'customers': [{'id': c.id, 'name': c.name, 'nickname': c.nickname, 'tpid': c.tpid, 
                       'tpid_url': c.tpid_url, 'territory_id': c.territory_id, 'seller_id': c.seller_id,
                       'vertical_ids': [v.id for v in c.verticals]} for c in Customer.query.all()],
        'topics': [{'id': t.id, 'name': t.name, 'description': t.description} for t in Topic.query.all()],
        'call_logs': [{'id': cl.id, 'customer_id': cl.customer_id, 'seller_id': cl.seller_id,
                       'territory_id': cl.territory_id, 'call_date': cl.call_date.isoformat(),
                       'content': cl.content, 'topic_ids': [t.id for t in cl.topics],
                       'created_at': cl.created_at.isoformat()} for cl in CallLog.query.all()]
    }
    
    response = app.response_class(
        response=json.dumps(data, indent=2),
        status=200,
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_backup_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json'
    return response


@app.route('/api/data-management/export/csv', methods=['GET'])
def export_full_csv():
    """Export complete database as CSV files in ZIP for spreadsheet analysis."""
    import csv
    import io
    import zipfile
    from datetime import datetime
    
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
            db.joinedload(CallLog.customer),
            db.joinedload(CallLog.seller),
            db.joinedload(CallLog.territory)
        ).all():
            topics = ', '.join([t.name for t in cl.topics])
            writer.writerow([cl.id, cl.call_date.isoformat(),
                           cl.customer.name if cl.customer else '',
                           cl.seller.name if cl.seller else '',
                           cl.territory.name if cl.territory else '',
                           cl.content, topics, cl.created_at.isoformat()])
        zip_file.writestr('call_logs.csv', csv_buffer.getvalue())
    
    zip_buffer.seek(0)
    response = app.response_class(
        response=zip_buffer.getvalue(),
        status=200,
        mimetype='application/zip'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=notehelper_backup_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.zip'
    return response


@app.route('/api/data-management/export/call-logs-json', methods=['GET'])
def export_call_logs_json():
    """Export call logs with enriched data as JSON for external analysis/LLM processing."""
    import json
    from datetime import datetime
    
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.verticals),
        db.joinedload(CallLog.seller),
        db.joinedload(CallLog.territory).joinedload(Territory.pod)
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
    
    response = app.response_class(
        response=json.dumps(data, indent=2),
        status=200,
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=call_logs_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.json'
    return response


@app.route('/api/data-management/export/call-logs-csv', methods=['GET'])
def export_call_logs_csv():
    """Export call logs with enriched data as CSV for spreadsheet analysis."""
    import csv
    import io
    from datetime import datetime
    
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.verticals),
        db.joinedload(CallLog.seller),
        db.joinedload(CallLog.territory).joinedload(Territory.pod)
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
    
    response = app.response_class(
        response=csv_buffer.getvalue(),
        status=200,
        mimetype='text/csv'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=call_logs_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# Import the streaming import endpoint
from import_api import create_import_endpoint
create_import_endpoint(app, db, Territory, Seller, POD, SolutionEngineer, Vertical, Customer)


# =============================================================================
# USER PREFERENCE ROUTES
# =============================================================================

@app.route('/api/preferences/dark-mode', methods=['GET', 'POST'])
def dark_mode_preference():
    """Get or set dark mode preference."""
    user_id = 1  # Single user system
    
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


@app.route('/api/preferences/customer-view', methods=['GET', 'POST'])
def customer_view_preference():
    """Get or set customer view preference (alphabetical vs grouped)."""
    user_id = 1  # Single user system
    
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


@app.route('/api/preferences/topic-sort', methods=['GET', 'POST'])
def topic_sort_preference():
    """Get or set topic sort preference (alphabetical vs by calls)."""
    user_id = 1  # Single user system
    
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


@app.route('/api/preferences/territory-view', methods=['GET', 'POST'])
def territory_view_preference():
    """Get or set territory view preference (recent calls vs accounts)."""
    user_id = 1  # Single user system
    
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


# =============================================================================
# Context Processor
# =============================================================================

@app.context_processor
def inject_preferences():
    """Inject user preferences into all templates."""
    user_id = 1  # Single user system
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    dark_mode = pref.dark_mode if pref else False
    customer_view_grouped = pref.customer_view_grouped if pref else False
    topic_sort_by_calls = pref.topic_sort_by_calls if pref else False
    return dict(dark_mode=dark_mode, customer_view_grouped=customer_view_grouped, topic_sort_by_calls=topic_sort_by_calls)


if __name__ == '__main__':
    app.run(debug=True)
