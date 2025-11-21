"""
Database models for NoteHelper application.
All SQLAlchemy models and association tables.
"""
from datetime import datetime, timezone, date
from typing import Optional
from flask_sqlalchemy import SQLAlchemy

# This will be initialized by the app factory
db = SQLAlchemy()


def utc_now():
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


# =============================================================================
# Association Tables
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


# =============================================================================
# User and Authentication Models
# =============================================================================

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


# =============================================================================
# Organizational Structure Models
# =============================================================================

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


# =============================================================================
# Customer and Call Log Models
# =============================================================================

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


# =============================================================================
# User Preferences Model
# =============================================================================

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
# AI Features Models
# =============================================================================

class AIConfig(db.Model):
    """Site-wide AI configuration for topic suggestion feature."""
    __tablename__ = 'ai_config'
    
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    endpoint_url = db.Column(db.String(500), nullable=True)
    api_key = db.Column(db.String(500), nullable=True)
    deployment_name = db.Column(db.String(100), nullable=True)
    api_version = db.Column(db.String(50), default='2024-08-01-preview', nullable=False)
    system_prompt = db.Column(db.Text, default=(
        "You are a helpful assistant that analyzes call notes and suggests relevant topic tags. "
        "Based on the call notes provided, return a JSON array of 3-7 short topic tags (1-3 words each) "
        "that best describe the key technologies, products, or themes discussed. "
        "Return ONLY a JSON array of strings, nothing else. "
        "Example: [\"Azure OpenAI\", \"Vector Search\", \"RAG Pattern\"]"
    ), nullable=False)
    max_daily_calls_per_user = db.Column(db.Integer, default=20, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    def __repr__(self) -> str:
        return f'<AIConfig enabled={self.enabled} deployment={self.deployment_name}>'


class AIUsage(db.Model):
    """Track daily AI API usage per user for rate limiting."""
    __tablename__ = 'ai_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=lambda: date.today())
    call_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Create unique constraint on user_id + date
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='unique_user_date'),
    )
    
    def __repr__(self) -> str:
        return f'<AIUsage user_id={self.user_id} date={self.date} calls={self.call_count}>'


class AIQueryLog(db.Model):
    """Audit log of all AI API calls for debugging and prompt improvement."""
    __tablename__ = 'ai_query_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False)
    request_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    
    # Relationship
    user = db.relationship('User', foreign_keys=[user_id])
    
    def __repr__(self) -> str:
        status = 'success' if self.success else 'failed'
        return f'<AIQueryLog user_id={self.user_id} {status} at {self.timestamp}>'
