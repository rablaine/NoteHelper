"""
NoteHelper - A note-taking application for Azure technical sellers.
Single-user Flask application for tracking customer call notes.
"""
import os
from datetime import datetime, timezone, date
from typing import Optional

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func, or_
from dotenv import load_dotenv
import msal
import requests

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

# Entra ID (Azure AD) OAuth configuration
app.config['AZURE_CLIENT_ID'] = os.getenv('AZURE_CLIENT_ID')
app.config['AZURE_CLIENT_SECRET'] = os.getenv('AZURE_CLIENT_SECRET')
app.config['AZURE_TENANT_ID'] = os.getenv('AZURE_TENANT_ID')
app.config['AZURE_REDIRECT_URI'] = os.getenv('AZURE_REDIRECT_URI', 'http://localhost:5000/auth/callback')
app.config['AZURE_AUTHORITY'] = f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID', 'common')}"
app.config['AZURE_SCOPE'] = ['User.Read']

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in with your Microsoft account to access this page.'

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


class User(db.Model):
    """User model for Entra ID (Azure AD) authentication.
    
    Supports multiple account types:
    - microsoft_azure_id: Corporate @microsoft.com account
    - external_azure_id: External tenant account (e.g., partner tenant)
    
    Users can log in with either account and will be associated with the same User record.
    Stub accounts are created when a new user attempts to link to an existing account.
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    microsoft_azure_id = db.Column(db.String(255), unique=True, nullable=True)  # @microsoft.com Entra object ID
    external_azure_id = db.Column(db.String(255), unique=True, nullable=True)  # External tenant Entra object ID
    email = db.Column(db.String(255), nullable=False)  # Primary email (not necessarily unique if using both account types)
    name = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)  # Admin flag for privileged users
    is_stub = db.Column(db.Boolean, default=False, nullable=False)  # True if this is a stub account awaiting linking
    linked_at = db.Column(db.DateTime, nullable=True)  # When the account linking was completed
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_login = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Flask-Login required properties
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_active(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    def get_id(self):
        return str(self.id)
    
    @property
    def account_type(self) -> str:
        """Return account type: 'microsoft', 'external', or 'dual'."""
        has_microsoft = self.microsoft_azure_id is not None
        has_external = self.external_azure_id is not None
        
        if has_microsoft and has_external:
            return 'dual'
        elif has_microsoft:
            return 'microsoft'
        elif has_external:
            return 'external'
        return 'unknown'
    
    def get_pending_link_requests(self):
        """Get all pending linking requests targeting this user's email."""
        return AccountLinkingRequest.query.filter_by(
            target_email=self.email,
            status='pending'
        ).order_by(AccountLinkingRequest.created_at.desc()).all()
    
    def __repr__(self) -> str:
        return f'<User {self.email}>'


class WhitelistedDomain(db.Model):
    """Domains allowed to access the system for non-@microsoft.com accounts."""
    __tablename__ = 'whitelisted_domains'
    
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False)  # e.g., 'partner.onmicrosoft.com'
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    @staticmethod
    def is_domain_allowed(email: str) -> bool:
        """Check if the email's domain is allowed."""
        if not email or '@' not in email:
            return False
        
        # @microsoft.com is always allowed
        if email.lower().endswith('@microsoft.com'):
            return True
        
        # Extract domain
        domain = email.split('@')[1].lower()
        
        # Check whitelist
        return WhitelistedDomain.query.filter_by(domain=domain).first() is not None
    
    def __repr__(self) -> str:
        return f'<WhitelistedDomain {self.domain}>'


class AccountLinkingRequest(db.Model):
    """Requests to link a stub account to an existing user account."""
    __tablename__ = 'account_linking_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    requesting_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)  # The stub account (NULL after merge)
    target_email = db.Column(db.String(255), nullable=False)  # Email of the account to link to
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'approved', 'denied'
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    requesting_user = db.relationship('User', foreign_keys=[requesting_user_id], backref='linking_requests_sent')
    resolved_by_user = db.relationship('User', foreign_keys=[resolved_by_user_id])
    
    def __repr__(self) -> str:
        return f'<AccountLinkingRequest from={self.requesting_user_id} to={self.target_email} status={self.status}>'


class POD(db.Model):
    """POD (Practice Operating Division) - organizational grouping of territories and personnel."""
    __tablename__ = 'pods'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, default=1)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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
    """Industry vertical for customer classification."""
    __tablename__ = 'verticals'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    customers = db.relationship(
        'Customer',
        secondary=customers_verticals,
        back_populates='verticals',
        lazy='select'
    )
    
    def __repr__(self) -> str:
        return f'<Vertical {self.name}>'


class Territory(db.Model):
    """Geographic or organizational territory for organizing customers and sellers."""
    __tablename__ = 'territories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    pod_id = db.Column(db.Integer, db.ForeignKey('pods.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    territories = db.relationship(
        'Territory',
        secondary=sellers_territories,
        back_populates='sellers',
        lazy='select'
    )
    customers = db.relationship('Customer', back_populates='seller', lazy='select')
    # Call logs can be accessed via Customer relationship
    
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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
    call_date = db.Column(db.Date, nullable=False, default=lambda: date.today())
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    customer = db.relationship('Customer', back_populates='call_logs')
    topics = db.relationship(
        'Topic',
        secondary=call_logs_topics,
        back_populates='call_logs',
        lazy='select'
    )
    
    @property
    def seller(self):
        """Get seller from customer relationship."""
        return self.customer.seller if self.customer else None
    
    @property
    def territory(self):
        """Get territory from customer relationship."""
        return self.customer.territory if self.customer else None
    
    def __repr__(self) -> str:
        return f'<CallLog {self.id} for {self.customer.name}>'


class UserPreference(db.Model):
    """User preferences including dark mode and customer view settings."""
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, default=1)  # Single user system
    dark_mode = db.Column(db.Boolean, default=False, nullable=False)
    customer_view_grouped = db.Column(db.Boolean, default=False, nullable=False)
    customer_sort_by = db.Column(db.String(20), default='alphabetical', nullable=False)  # 'alphabetical', 'grouped', or 'by_calls'
    topic_sort_by_calls = db.Column(db.Boolean, default=False, nullable=False)
    territory_view_accounts = db.Column(db.Boolean, default=False, nullable=False)  # False = recent calls, True = accounts
    colored_sellers = db.Column(db.Boolean, default=True, nullable=False)  # False = grey sellers, True = colored sellers
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    def __repr__(self) -> str:
        return f'<UserPreference user_id={self.user_id} dark_mode={self.dark_mode} customer_view_grouped={self.customer_view_grouped} customer_sort_by={self.customer_sort_by} topic_sort_by_calls={self.topic_sort_by_calls} territory_view_accounts={self.territory_view_accounts} colored_sellers={self.colored_sellers}>'


# =============================================================================
# Flask-Login Configuration
# =============================================================================

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login."""
    return User.query.get(int(user_id))


@app.before_request
def require_login():
    """Require login for all routes except auth routes and static files."""
    # If user is logged in but is a stub account, restrict access to only account linking routes
    # This check happens BEFORE LOGIN_DISABLED check so tests can verify stub restrictions
    if current_user.is_authenticated and current_user.is_stub:
        stub_allowed_routes = ['account_link_status', 'first_time_flow', 'first_time_new_user', 
                              'first_time_link_request', 'user_profile', 'logout', 'static']
        if request.endpoint not in stub_allowed_routes:
            return redirect(url_for('account_link_status'))
    
    # Skip auth check if LOGIN_DISABLED is set (for testing)
    if app.config.get('LOGIN_DISABLED'):
        return None
    
    # Allow access to auth routes, first-time flow, domain not allowed page, and static files
    allowed_routes = ['login', 'auth_callback', 'first_time_flow', 'first_time_new_user', 
                     'first_time_link_request', 'domain_not_allowed', 'static']
    
    if request.endpoint not in allowed_routes and not current_user.is_authenticated:
        return redirect(url_for('login'))


# =============================================================================
# Authentication Routes
# =============================================================================

@app.route('/login')
def login():
    """Show login page or redirect to Entra ID login."""
    # If already authenticated, redirect to home
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    # Check if Entra ID is configured
    if not app.config.get('AZURE_CLIENT_ID') or app.config['AZURE_CLIENT_ID'] == 'your-azure-client-id':
        # Entra ID not configured - show login page with instructions
        flash('Entra ID authentication is not configured. Please set up your Entra ID credentials in .env file.', 'warning')
        return render_template('login.html')
    
    # Create MSAL confidential client
    msal_app = msal.ConfidentialClientApplication(
        app.config['AZURE_CLIENT_ID'],
        authority=app.config['AZURE_AUTHORITY'],
        client_credential=app.config['AZURE_CLIENT_SECRET']
    )
    
    # Generate auth URL
    auth_url = msal_app.get_authorization_request_url(
        scopes=app.config['AZURE_SCOPE'],
        redirect_uri=app.config['AZURE_REDIRECT_URI']
    )
    
    return redirect(auth_url)


@app.route('/domain-not-allowed')
def domain_not_allowed():
    """Show error page for non-whitelisted domains."""
    email = request.args.get('email', 'your email')
    return render_template('domain_not_allowed.html', email=email)


@app.route('/auth/callback')
def auth_callback():
    """Handle Entra ID OAuth callback with domain whitelist and account linking support."""
    # Get authorization code from query params
    code = request.args.get('code')
    if not code:
        flash('Authentication failed: No authorization code received.', 'danger')
        return redirect(url_for('login'))
    
    # Create MSAL confidential client
    msal_app = msal.ConfidentialClientApplication(
        app.config['AZURE_CLIENT_ID'],
        authority=app.config['AZURE_AUTHORITY'],
        client_credential=app.config['AZURE_CLIENT_SECRET']
    )
    
    # Exchange code for token
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=app.config['AZURE_SCOPE'],
        redirect_uri=app.config['AZURE_REDIRECT_URI']
    )
    
    if 'error' in result:
        flash(f"Authentication failed: {result.get('error_description', 'Unknown error')}", 'danger')
        return redirect(url_for('login'))
    
    # Get user info from Microsoft Graph
    access_token = result['access_token']
    graph_response = requests.get(
        'https://graph.microsoft.com/v1.0/me',
        headers={'Authorization': f'Bearer {access_token}'}
    )
    
    if graph_response.status_code != 200:
        flash('Failed to retrieve user information from Microsoft Graph.', 'danger')
        return redirect(url_for('login'))
    
    user_info = graph_response.json()
    azure_id = user_info['id']
    email = user_info.get('mail') or user_info.get('userPrincipalName')
    name = user_info.get('displayName', email)
    
    # Check if domain is whitelisted (for non-@microsoft.com accounts)
    if not WhitelistedDomain.is_domain_allowed(email):
        # Domain not allowed - redirect to error page
        return redirect(url_for('domain_not_allowed', email=email))
    
    # Determine account type based on email domain
    is_microsoft_account = email.lower().endswith('@microsoft.com')
    
    # Try to find existing user by either azure_id (handles dual accounts)
    if is_microsoft_account:
        user = User.query.filter_by(microsoft_azure_id=azure_id).first()
    else:
        user = User.query.filter_by(external_azure_id=azure_id).first()
    
    if not user:
        # New Azure ID - check if there's an existing full account with this email
        # that might be waiting to link with this account type
        existing_full_account = User.query.filter_by(email=email, is_stub=False).first()
        
        if existing_full_account:
            # There's a full account with this email - check if they have the other account type
            if is_microsoft_account and not existing_full_account.microsoft_azure_id:
                # This is a Microsoft account trying to link to an external-only account
                # Redirect to first-time flow to ask if they want to link
                session['pending_auth'] = {
                    'azure_id': azure_id,
                    'email': email,
                    'name': name,
                    'is_microsoft': is_microsoft_account
                }
                return redirect(url_for('first_time_flow'))
            elif not is_microsoft_account and not existing_full_account.external_azure_id:
                # This is an external account trying to link to a Microsoft-only account
                session['pending_auth'] = {
                    'azure_id': azure_id,
                    'email': email,
                    'name': name,
                    'is_microsoft': is_microsoft_account
                }
                return redirect(url_for('first_time_flow'))
        
        # No existing account or incompatible account - show first-time flow
        session['pending_auth'] = {
            'azure_id': azure_id,
            'email': email,
            'name': name,
            'is_microsoft': is_microsoft_account
        }
        return redirect(url_for('first_time_flow'))
    
    # User exists - update last login
    user.last_login = utc_now()
    user.name = name  # Update name in case it changed
    
    # If this is a stub account, remind them they need to complete linking
    if user.is_stub:
        db.session.commit()
        login_user(user)
        flash('You are logged into a temporary account. Please complete the account linking process.', 'warning')
        return redirect(url_for('account_link_status'))
    
    db.session.commit()
    
    # Log user in
    login_user(user)
    
    # Check if there are pending link requests for this user
    pending_requests = user.get_pending_link_requests()
    if pending_requests:
        flash(f'You have {len(pending_requests)} pending account linking request(s). Please review them in your profile.', 'info')
    
    flash(f'Welcome back, {user.name}!', 'success')
    return redirect(url_for('index'))


@app.route('/logout')
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash('You have been logged out.', 'info')
    
    # Redirect to Entra ID logout (optional - clears Entra ID session too)
    logout_url = f"{app.config['AZURE_AUTHORITY']}/oauth2/v2.0/logout?post_logout_redirect_uri={request.host_url}"
    return redirect(logout_url)


@app.route('/profile')
@login_required
def user_profile():
    """Display current user's profile information and pending link requests."""
    # Get pending link requests for this user's email
    pending_requests = current_user.get_pending_link_requests() if not current_user.is_stub else []
    
    return render_template('user_profile.html', 
                         user=current_user,
                         pending_requests=pending_requests)


# =============================================================================
# Admin Routes
# =============================================================================

@app.route('/admin')
@login_required
def admin_panel():
    """Admin control panel for managing users and system-wide operations."""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    
    # Get all users
    users = User.query.order_by(User.created_at.desc()).all()
    
    # Get system-wide statistics
    stats = {
        'total_users': User.query.count(),
        'total_pods': POD.query.count(),
        'total_territories': Territory.query.count(),
        'total_sellers': Seller.query.count(),
        'total_customers': Customer.query.count(),
        'total_topics': Topic.query.count(),
        'total_call_logs': CallLog.query.count()
    }
    
    return render_template('admin_panel.html', users=users, stats=stats)


@app.route('/api/admin/grant-admin/<int:user_id>', methods=['POST'])
@login_required
def api_grant_admin(user_id):
    """Grant admin privileges to a user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'{user.name} is now an admin'})


@app.route('/api/admin/revoke-admin/<int:user_id>', methods=['POST'])
@login_required
def api_revoke_admin(user_id):
    """Revoke admin privileges from a user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Prevent revoking your own admin
    if user_id == current_user.id:
        return jsonify({'error': 'You cannot revoke your own admin privileges'}), 400
    
    user = User.query.get_or_404(user_id)
    user.is_admin = False
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'{user.name} is no longer an admin'})


@app.route('/admin/domains')
@login_required
def admin_domains():
    """Manage whitelisted domains."""
    if not current_user.is_admin:
        flash('You do not have permission to access domain management.', 'danger')
        return redirect(url_for('index'))
    
    domains = WhitelistedDomain.query.order_by(WhitelistedDomain.domain).all()
    return render_template('admin_domains.html', domains=domains)


@app.route('/api/admin/domain/add', methods=['POST'])
@login_required
def api_admin_domain_add():
    """Add a domain to the whitelist."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    domain = data.get('domain', '').strip().lower()
    
    if not domain:
        return jsonify({'error': 'Domain is required'}), 400
    
    # Basic validation
    if '@' in domain or not '.' in domain:
        return jsonify({'error': 'Invalid domain format. Enter just the domain (e.g., partner.onmicrosoft.com)'}), 400
    
    # Check if already exists
    existing = WhitelistedDomain.query.filter_by(domain=domain).first()
    if existing:
        return jsonify({'error': f'Domain {domain} is already whitelisted'}), 400
    
    # Add domain
    try:
        new_domain = WhitelistedDomain(domain=domain, added_by_user_id=current_user.id)
        db.session.add(new_domain)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Domain {domain} added to whitelist',
            'domain': {'id': new_domain.id, 'domain': new_domain.domain, 'created_at': new_domain.created_at.isoformat()}
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error adding domain: {str(e)}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@app.route('/api/admin/domain/remove/<int:domain_id>', methods=['POST'])
@login_required
def api_admin_domain_remove(domain_id):
    """Remove a domain from the whitelist."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    domain = WhitelistedDomain.query.get_or_404(domain_id)
    domain_name = domain.domain
    
    db.session.delete(domain)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Domain {domain_name} removed from whitelist'})


# =============================================================================
# Account Linking Routes
# =============================================================================

@app.route('/account/first-time')
def first_time_flow():
    """First-time login flow to determine if user wants to create new account or link to existing."""
    # Check if there's pending auth data in session
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('login'))
    
    return render_template('first_time_flow.html',
                         email=pending_auth['email'],
                         name=pending_auth['name'],
                         is_microsoft=pending_auth['is_microsoft'])


@app.route('/account/first-time/new', methods=['POST'])
def first_time_new_user():
    """Create a new user account (first-time user with no existing data)."""
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('login'))
    
    # Create new user account
    if pending_auth['is_microsoft']:
        user = User(
            microsoft_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            name=pending_auth['name']
        )
    else:
        user = User(
            external_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            name=pending_auth['name']
        )
    
    db.session.add(user)
    db.session.commit()
    
    # Create default user preferences
    pref = UserPreference(user_id=user.id)
    db.session.add(pref)
    db.session.commit()
    
    # Clear pending auth
    session.pop('pending_auth', None)
    
    # Log user in
    login_user(user)
    flash(f'Welcome, {user.name}! Your account has been created.', 'success')
    
    return redirect(url_for('index'))


@app.route('/account/first-time/link', methods=['POST'])
def first_time_link_request():
    """Create a linking request to an existing account."""
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('login'))
    
    target_email = request.form.get('target_email', '').strip()
    
    if not target_email or '@' not in target_email:
        flash('Please enter a valid email address.', 'danger')
        return redirect(url_for('first_time_flow'))
    
    # Check if target email exists
    target_user = User.query.filter_by(email=target_email, is_stub=False).first()
    if not target_user:
        flash(f'No account found with email {target_email}. Double-check the spelling, or create a new account if this is your first time using the app.', 'warning')
        return redirect(url_for('first_time_flow'))
    
    # Check if target user already has this account type linked
    is_microsoft = pending_auth['is_microsoft']
    if is_microsoft and target_user.microsoft_azure_id:
        flash(f'The account {target_email} already has a Microsoft account linked. Cannot link another Microsoft account.', 'danger')
        return redirect(url_for('first_time_flow'))
    if not is_microsoft and target_user.external_azure_id:
        flash(f'The account {target_email} already has an external account linked. Cannot link another external account.', 'danger')
        return redirect(url_for('first_time_flow'))
    
    # Create stub user
    if is_microsoft:
        stub_user = User(
            microsoft_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            name=pending_auth['name'],
            is_stub=True
        )
    else:
        stub_user = User(
            external_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            name=pending_auth['name'],
            is_stub=True
        )
    
    db.session.add(stub_user)
    db.session.flush()
    
    # Cancel any existing pending requests from this stub to the same target
    AccountLinkingRequest.query.filter_by(
        requesting_user_id=stub_user.id,
        target_email=target_email,
        status='pending'
    ).update({'status': 'cancelled', 'resolved_at': utc_now()})
    
    # Create linking request
    link_request = AccountLinkingRequest(
        requesting_user_id=stub_user.id,
        target_email=target_email
    )
    db.session.add(link_request)
    db.session.commit()
    
    # Clear pending auth
    session.pop('pending_auth', None)
    
    # Log stub user in
    login_user(stub_user)
    
    flash(f'Linking request sent to {target_email}. Please log in with that account to approve the request.', 'success')
    return redirect(url_for('account_link_status'))


@app.route('/account/link-status')
@login_required
def account_link_status():
    """Show status of account linking for stub users."""
    if not current_user.is_stub:
        return redirect(url_for('user_profile'))
    
    # Get pending requests
    requests = AccountLinkingRequest.query.filter_by(
        requesting_user_id=current_user.id,
        status='pending'
    ).all()
    
    return render_template('account_link_status.html', requests=requests)


@app.route('/account/link/approve/<int:request_id>', methods=['POST'])
@login_required
def account_link_approve(request_id):
    """Approve a linking request and merge the stub account."""
    link_request = AccountLinkingRequest.query.get_or_404(request_id)
    
    # Verify this request is for the current user
    if link_request.target_email != current_user.email:
        flash('You cannot approve a linking request not intended for you.', 'danger')
        return redirect(url_for('user_profile'))
    
    # Verify request is still pending
    if link_request.status != 'pending':
        flash('This linking request has already been processed.', 'info')
        return redirect(url_for('user_profile'))
    
    # Get the stub user
    stub_user = db.session.get(User, link_request.requesting_user_id)
    if not stub_user or not stub_user.is_stub:
        flash('Invalid linking request.', 'danger')
        return redirect(url_for('user_profile'))
    
    # Check if current user already has this account type
    if stub_user.microsoft_azure_id and current_user.microsoft_azure_id:
        flash('You already have a Microsoft account linked.', 'danger')
        return redirect(url_for('user_profile'))
    if stub_user.external_azure_id and current_user.external_azure_id:
        flash('You already have an external account linked.', 'danger')
        return redirect(url_for('user_profile'))
    
    # Clear stub's azure_ids before merging to avoid UNIQUE constraint violation
    stub_microsoft_id = stub_user.microsoft_azure_id
    stub_external_id = stub_user.external_azure_id
    stub_user.microsoft_azure_id = None
    stub_user.external_azure_id = None
    db.session.flush()  # Flush to release the UNIQUE constraint
    
    # Merge the accounts
    if stub_microsoft_id:
        current_user.microsoft_azure_id = stub_microsoft_id
    if stub_external_id:
        current_user.external_azure_id = stub_external_id
    
    current_user.linked_at = utc_now()
    
    # Save stub_id for deletion
    stub_user_id = stub_user.id
    
    # Mark request as approved
    link_request.status = 'approved'
    link_request.resolved_at = utc_now()
    link_request.resolved_by_user_id = current_user.id
    
    # Commit the merge and approval
    db.session.commit()
    
    # Delete stub user using raw SQL to preserve the foreign key in account_linking_requests
    # (Using ORM delete would NULL the FK)
    db.session.execute(db.text('DELETE FROM users WHERE id = :id'), {'id': stub_user_id})
    db.session.commit()
    
    flash('Account linked successfully! You can now log in with either account.', 'success')
    return redirect(url_for('user_profile'))


@app.route('/account/link/deny/<int:request_id>', methods=['POST'])
@login_required
def account_link_deny(request_id):
    """Deny a linking request."""
    link_request = AccountLinkingRequest.query.get_or_404(request_id)
    
    # Verify this request is for the current user
    if link_request.target_email != current_user.email:
        flash('You cannot deny a linking request not intended for you.', 'danger')
        return redirect(url_for('user_profile'))
    
    # Verify request is still pending
    if link_request.status != 'pending':
        flash('This linking request has already been processed.', 'info')
        return redirect(url_for('user_profile'))
    
    # Mark request as denied
    link_request.status = 'denied'
    link_request.resolved_at = utc_now()
    link_request.resolved_by_user_id = current_user.id
    
    db.session.commit()
    
    flash('Linking request denied.', 'info')
    return redirect(url_for('user_profile'))


# =============================================================================
# Routes
# =============================================================================

@app.route('/')
@login_required
def index():
    """Home page showing recent activity and stats."""
    # Eager load relationships for recent calls to avoid N+1 queries
    recent_calls = CallLog.query.filter_by(user_id=current_user.id).options(
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory),
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).limit(10).all()
    
    # Count queries are fast on these small tables
    stats = {
        'call_logs': CallLog.query.filter_by(user_id=current_user.id).count(),
        'customers': Customer.query.filter_by(user_id=current_user.id).count(),
        'sellers': Seller.query.filter_by(user_id=current_user.id).count(),
        'topics': Topic.query.filter_by(user_id=current_user.id).count()
    }
    return render_template('index.html', recent_calls=recent_calls, stats=stats)


# =============================================================================
# Territory Routes (FR001, FR006)
# =============================================================================

@app.route('/territories')
def territories_list():
    """List all territories."""
    territories = Territory.query.filter_by(user_id=current_user.id).options(
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
        existing = Territory.query.filter_by(name=name, user_id=current_user.id).first()
        if existing:
            flash(f'Territory "{name}" already exists.', 'warning')
            return redirect(url_for('territory_view', id=existing.id))
        
        territory = Territory(name=name, user_id=current_user.id)
        db.session.add(territory)
        db.session.commit()
        
        flash(f'Territory "{name}" created successfully!', 'success')
        return redirect(url_for('territories_list'))
    
    # Show existing territories to prevent duplicates
    existing_territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    return render_template('territory_form.html', territory=None, existing_territories=existing_territories)


@app.route('/territory/<int:id>')
def territory_view(id):
    """View territory details (FR006)."""
    territory = Territory.query.filter_by(user_id=current_user.id).options(
        db.joinedload(Territory.pod)
    ).filter_by(id=id).first_or_404()
    # Sort sellers in-memory since they're eager-loaded
    sellers = sorted(territory.sellers, key=lambda s: s.name)
    
    # Get user preference for territory view
    user_id = current_user.id if current_user.is_authenticated else 1
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
        recent_calls = CallLog.query.filter_by(user_id=current_user.id).join(Customer).filter(
            Customer.territory_id == id,
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
    territory = Territory.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        
        if not name:
            flash('Territory name is required.', 'danger')
            return redirect(url_for('territory_edit', id=id))
        
        # Check for duplicate (excluding current territory)
        existing = Territory.query.filter_by(user_id=current_user.id).filter(
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
    
    existing_territories = Territory.query.filter_by(user_id=current_user.id).filter(Territory.id != id).order_by(Territory.name).all()
    return render_template('territory_form.html', territory=territory, existing_territories=existing_territories)


# =============================================================================
# POD Routes
# =============================================================================

@app.route('/pods')
def pods_list():
    """List all PODs."""
    pods = POD.query.filter_by(user_id=current_user.id).options(
        db.joinedload(POD.territories),
        db.joinedload(POD.solution_engineers)
    ).order_by(POD.name).all()
    return render_template('pods_list.html', pods=pods)


@app.route('/pod/<int:id>')
def pod_view(id):
    """View POD details with territories, sellers, and solution engineers."""
    # Use selectinload for better performance with collections
    pod = POD.query.filter_by(user_id=current_user.id).options(
        db.selectinload(POD.territories).selectinload(Territory.sellers),
        db.selectinload(POD.solution_engineers)
    ).filter_by(id=id).first_or_404()
    
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
    pod = POD.query.filter_by(user_id=current_user.id).options(
        db.selectinload(POD.territories),
        db.selectinload(POD.solution_engineers)
    ).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_ids = request.form.getlist('territory_ids')
        se_ids = request.form.getlist('se_ids')
        
        if not name:
            flash('POD name is required.', 'danger')
            return redirect(url_for('pod_edit', id=id))
        
        # Check for duplicate
        existing = POD.query.filter_by(user_id=current_user.id).filter(POD.name == name, POD.id != id).first()
        if existing:
            flash(f'POD "{name}" already exists.', 'warning')
            return redirect(url_for('pod_view', id=existing.id))
        
        pod.name = name
        
        # Update territories
        pod.territories.clear()
        for territory_id in territory_ids:
            territory = Territory.query.filter_by(user_id=current_user.id).get(int(territory_id))
            if territory:
                pod.territories.append(territory)
        
        # Update solution engineers
        pod.solution_engineers.clear()
        for se_id in se_ids:
            se = SolutionEngineer.query.filter_by(user_id=current_user.id).get(int(se_id))
            if se:
                pod.solution_engineers.append(se)
        
        db.session.commit()
        
        flash(f'POD "{name}" updated successfully!', 'success')
        return redirect(url_for('pod_view', id=pod.id))
    
    # Get all territories and solution engineers for the form
    all_territories = Territory.query.filter_by(user_id=current_user.id).options(
        db.selectinload(Territory.sellers)
    ).order_by(Territory.name).all()
    all_ses = SolutionEngineer.query.filter_by(user_id=current_user.id).order_by(SolutionEngineer.name).all()
    
    return render_template('pod_form.html', pod=pod, all_territories=all_territories, all_ses=all_ses)


# =============================================================================
# Solution Engineer Routes
# =============================================================================

@app.route('/solution-engineers')
def solution_engineers_list():
    """List all solution engineers."""
    ses = SolutionEngineer.query.filter_by(user_id=current_user.id).options(
        db.joinedload(SolutionEngineer.pods)
    ).order_by(SolutionEngineer.name).all()
    return render_template('solution_engineers_list.html', solution_engineers=ses)


@app.route('/solution-engineer/<int:id>')
def solution_engineer_view(id):
    """View solution engineer details."""
    se = SolutionEngineer.query.filter_by(user_id=current_user.id).options(
        db.joinedload(SolutionEngineer.pods)
    ).filter_by(id=id).first_or_404()
    
    # Sort PODs
    pods = sorted(se.pods, key=lambda p: p.name)
    
    return render_template('solution_engineer_view.html',
                         solution_engineer=se,
                         pods=pods)


@app.route('/solution-engineer/<int:id>/edit', methods=['GET', 'POST'])
def solution_engineer_edit(id):
    """Edit solution engineer details."""
    se = SolutionEngineer.query.filter_by(user_id=current_user.id).options(
        db.joinedload(SolutionEngineer.pods)
    ).filter_by(id=id).first_or_404()
    
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
            pod = POD.query.filter_by(user_id=current_user.id).get(int(pod_id))
            if pod:
                se.pods.append(pod)
        
        db.session.commit()
        
        flash(f'Solution Engineer "{name}" updated successfully!', 'success')
        return redirect(url_for('solution_engineer_view', id=se.id))
    
    # Get all PODs for the form
    all_pods = POD.query.filter_by(user_id=current_user.id).order_by(POD.name).all()
    return render_template('solution_engineer_form.html', solution_engineer=se, all_pods=all_pods)


# =============================================================================
# Seller Routes (FR002, FR007)
# =============================================================================

@app.route('/sellers')
def sellers_list():
    """List all sellers."""
    sellers = Seller.query.filter_by(user_id=current_user.id).options(
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
        existing = Seller.query.filter_by(name=name, user_id=current_user.id).first()
        if existing:
            flash(f'Seller "{name}" already exists.', 'warning')
            return redirect(url_for('seller_view', id=existing.id))
        
        seller = Seller(name=name, user_id=current_user.id)
        
        # Add territories to many-to-many relationship
        if territory_ids:
            for territory_id in territory_ids:
                territory = Territory.query.filter_by(user_id=current_user.id).get(int(territory_id))
                if territory:
                    seller.territories.append(territory)
        
        db.session.add(seller)
        db.session.commit()
        
        flash(f'Seller "{name}" created successfully!', 'success')
        return redirect(url_for('sellers_list'))
    
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    existing_sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    return render_template('seller_form.html', seller=None, territories=territories, existing_sellers=existing_sellers)


@app.route('/seller/<int:id>')
def seller_view(id):
    """View seller details (FR007)."""
    seller = Seller.query.filter_by(user_id=current_user.id).options(
        db.joinedload(Seller.customers).joinedload(Customer.call_logs)
    ).filter_by(id=id).first_or_404()
    
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
    seller = Seller.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        territory_ids = request.form.getlist('territory_ids')
        
        if not name:
            flash('Seller name is required.', 'danger')
            return redirect(url_for('seller_edit', id=id))
        
        # Check for duplicate (excluding current seller)
        existing = Seller.query.filter_by(user_id=current_user.id).filter(
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
                territory = Territory.query.filter_by(user_id=current_user.id).get(int(territory_id))
                if territory:
                    seller.territories.append(territory)
        
        db.session.commit()
        
        flash(f'Seller "{name}" updated successfully!', 'success')
        return redirect(url_for('seller_view', id=seller.id))
    
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    existing_sellers = Seller.query.filter_by(user_id=current_user.id).filter(Seller.id != id).order_by(Seller.name).all()
    return render_template('seller_form.html', seller=seller, territories=territories, existing_sellers=existing_sellers)


@app.route('/territory/create-inline', methods=['POST'])
def territory_create_inline():
    """Create territory inline from other forms."""
    name = request.form.get('name', '').strip()
    redirect_to = request.form.get('redirect_to', url_for('territories_list'))
    
    if name:
        existing = Territory.query.filter_by(name=name, user_id=current_user.id).first()
        if not existing:
            territory = Territory(name=name, user_id=current_user.id)
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
            territory_id=int(territory_id) if territory_id else None,
            user_id=current_user.id
        )
        db.session.add(customer)
        db.session.commit()
        
        flash(f'Customer "{name}" created successfully!', 'success')
        
        # Redirect back to referrer (FR031)
        if referrer:
            return redirect(referrer)
        
        return redirect(url_for('customer_view', id=customer.id))
    
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


@app.route('/customer/<int:id>')
def customer_view(id):
    """View customer details (FR008)."""
    customer = Customer.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    # Sort call logs by date (descending) - customer.call_logs is already loaded as a list
    call_logs = sorted(customer.call_logs, key=lambda c: c.call_date, reverse=True)
    return render_template('customer_view.html', customer=customer, call_logs=call_logs)


@app.route('/customer/<int:id>/edit', methods=['GET', 'POST'])
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
    
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    
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
        existing = Seller.query.filter_by(name=name, user_id=current_user.id).first()
        if not existing:
            seller = Seller(name=name, user_id=current_user.id)
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
    user_id = current_user.id if current_user.is_authenticated else 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    
    # Load topics with eager loading
    topics = Topic.query.filter_by(user_id=current_user.id).options(db.joinedload(Topic.call_logs)).all()
    
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
    existing = Topic.query.filter_by(user_id=current_user.id).filter(func.lower(Topic.name) == func.lower(name)).first()
    if existing:
        return jsonify({
            'id': existing.id,
            'name': existing.name,
            'description': existing.description or '',
            'existed': True
        }), 200
    
    # Create new topic
    topic = Topic(name=name, description=None, user_id=current_user.id)
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
        existing = Topic.query.filter_by(name=name, user_id=current_user.id).first()
        if existing:
            flash(f'Topic "{name}" already exists.', 'warning')
            return redirect(url_for('topic_view', id=existing.id))
        
        topic = Topic(
            name=name,
            description=description if description else None,
            user_id=current_user.id
        )
        db.session.add(topic)
        db.session.commit()
        
        flash(f'Topic "{name}" created successfully!', 'success')
        return redirect(url_for('topics_list'))
    
    return render_template('topic_form.html', topic=None)


@app.route('/topic/<int:id>')
def topic_view(id):
    """View topic details (FR009)."""
    topic = Topic.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    # Sort call logs in-memory since they're eager-loaded
    call_logs = sorted(topic.call_logs, key=lambda c: c.call_date, reverse=True)
    return render_template('topic_view.html', topic=topic, call_logs=call_logs)


@app.route('/topic/<int:id>/edit', methods=['GET', 'POST'])
def topic_edit(id):
    """Edit topic (FR009)."""
    topic = Topic.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash('Topic name is required.', 'danger')
            return redirect(url_for('topic_edit', id=id))
        
        # Check for duplicate topic names (excluding current topic)
        existing = Topic.query.filter_by(user_id=current_user.id).filter(Topic.name == name, Topic.id != id).first()
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
    topic = Topic.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
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
    call_logs = CallLog.query.filter_by(user_id=current_user.id).options(
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory),
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
        
        return redirect(url_for('call_log_view', id=call_log.id))
    
    # GET request - load form
    # Require customer_id to be specified
    preselect_customer_id = request.args.get('customer_id', type=int)
    
    if not preselect_customer_id:
        # Redirect to customers list to select a customer first
        flash('Please select a customer before creating a call log.', 'info')
        return redirect(url_for('customers_list'))
    
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


@app.route('/call-log/<int:id>')
def call_log_view(id):
    """View call log details (FR010)."""
    call_log = CallLog.query.filter_by(user_id=current_user.id).filter_by(id=id).first_or_404()
    return render_template('call_log_view.html', call_log=call_log)


@app.route('/call-log/<int:id>/edit', methods=['GET', 'POST'])
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
        return redirect(url_for('call_log_view', id=call_log.id))
    
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
    
    # Check if any search criteria provided
    has_search = bool(search_text or customer_id or seller_id or territory_id or topic_ids)
    
    call_logs = []
    grouped_data = {}
    
    # Only perform search if criteria provided
    if has_search:
        # Start with base query filtered by user
        query = CallLog.query.filter_by(user_id=current_user.id)
        
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
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    sellers = Seller.query.filter_by(user_id=current_user.id).order_by(Seller.name).all()
    territories = Territory.query.filter_by(user_id=current_user.id).order_by(Territory.name).all()
    topics = Topic.query.filter_by(user_id=current_user.id).order_by(Topic.name).all()
    
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
    user_id = current_user.id if current_user.is_authenticated else 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.session.add(pref)
        db.session.commit()
    
    return render_template('preferences.html', 
                         dark_mode=pref.dark_mode,
                         customer_view_grouped=pref.customer_view_grouped,
                         customer_sort_by=pref.customer_sort_by,
                         topic_sort_by_calls=pref.topic_sort_by_calls,
                         territory_view_accounts=pref.territory_view_accounts,
                         colored_sellers=pref.colored_sellers)


@app.route('/data-management')
def data_management():
    """Data import/export management page."""
    # Check if database has any data
    has_data = (Customer.query.count() > 0 or 
                CallLog.query.count() > 0 or 
                POD.query.count() > 0 or
                Territory.query.count() > 0 or
                Seller.query.count() > 0)
    return render_template('data_management.html', has_data=has_data)


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
        'call_logs': [{'id': cl.id, 'customer_id': cl.customer_id,
                       'call_date': cl.call_date.isoformat(),
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
    
    call_logs = CallLog.query.filter_by(user_id=current_user.id).options(
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
    
    call_logs = CallLog.query.filter_by(user_id=current_user.id).options(
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
    # Get user ID (handle testing mode where login is disabled)
    user_id = current_user.id if current_user.is_authenticated else 1
    
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


@app.route('/tpid-workflow')
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


@app.route('/tpid-workflow/update', methods=['POST'])
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
            return redirect(url_for('tpid_workflow'))
        
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
    
    return redirect(url_for('tpid_workflow'))


@app.route('/api/preferences/customer-view', methods=['GET', 'POST'])
def customer_view_preference():
    """Get or set customer view preference (alphabetical vs grouped)."""
    user_id = current_user.id if current_user.is_authenticated else 1
    
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
    user_id = current_user.id if current_user.is_authenticated else 1
    
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
    user_id = current_user.id if current_user.is_authenticated else 1
    
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


@app.route('/api/preferences/colored-sellers', methods=['GET', 'POST'])
def colored_sellers_preference():
    """Get or set colored sellers preference (grey vs colored badges)."""
    user_id = current_user.id if current_user.is_authenticated else 1
    
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


@app.route('/api/preferences/customer-sort-by', methods=['GET', 'POST'])
def customer_sort_by_preference():
    """Get or set customer sorting preference (alphabetical, grouped, or by_calls)."""
    user_id = current_user.id if current_user.is_authenticated else 1
    
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


# =============================================================================
# Context Processor
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


@app.context_processor
def inject_preferences():
    """Inject user preferences and pending link requests into all templates."""
    pref = UserPreference.query.filter_by(user_id=current_user.id).first() if current_user.is_authenticated else None
    dark_mode = pref.dark_mode if pref else False
    customer_view_grouped = pref.customer_view_grouped if pref else False
    topic_sort_by_calls = pref.topic_sort_by_calls if pref else False
    colored_sellers = pref.colored_sellers if pref else True
    
    # Get pending link requests count
    pending_link_requests_count = 0
    if current_user.is_authenticated and not current_user.is_stub:
        pending_link_requests_count = len(current_user.get_pending_link_requests())
    
    # Create a wrapper function that includes the colored_sellers preference
    def get_seller_color_with_pref(seller_id: int) -> str:
        return get_seller_color(seller_id, colored_sellers)
    
    return dict(
        dark_mode=dark_mode, 
        customer_view_grouped=customer_view_grouped, 
        topic_sort_by_calls=topic_sort_by_calls,
        colored_sellers=colored_sellers,
        get_seller_color=get_seller_color_with_pref,
        pending_link_requests_count=pending_link_requests_count
    )


if __name__ == '__main__':
    app.run(debug=True)
