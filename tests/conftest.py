"""
Pytest configuration and fixtures for NoteHelper tests.
"""
import pytest
import tempfile
import os
from datetime import datetime, timezone


@pytest.fixture(scope='session')
def app():
    """Create application for testing with isolated database."""
    # Save original environment variables to restore later
    original_database_url = os.environ.get('DATABASE_URL')
    original_testing = os.environ.get('TESTING')
    
    # Create a temporary database file for testing
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    
    # Set test database URI BEFORE importing app
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
    os.environ['TESTING'] = 'true'
    
    # NOW import app - it will use the test database URI
    from app import app as flask_app, db, UserPreference, User, login_manager
    
    # Configure additional test settings
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['LOGIN_DISABLED'] = True  # Disable login requirement for tests
    
    # Create tables
    with flask_app.app_context():
        db.create_all()
        
        # Create test user with Microsoft account
        test_user = User(
            microsoft_azure_id='test-user-12345',
            email='test@microsoft.com',
            name='Test User'
        )
        db.session.add(test_user)
        db.session.flush()
        
        # Create default user preference
        pref = UserPreference(user_id=test_user.id, dark_mode=False, customer_view_grouped=False, topic_sort_by_calls=False, territory_view_accounts=False)
        db.session.add(pref)
        db.session.commit()
    
    yield flask_app
    
    # Cleanup
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
    os.close(db_fd)
    
    # Try to delete temp file, but ignore Windows file locking errors
    try:
        os.unlink(db_path)
    except (PermissionError, OSError):
        # Windows may keep the file locked; it will be cleaned up by OS temp cleanup
        pass
    
    # Restore original environment variables
    if original_database_url is not None:
        os.environ['DATABASE_URL'] = original_database_url
    elif 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']
    
    if original_testing is not None:
        os.environ['TESTING'] = original_testing
    elif 'TESTING' in os.environ:
        del os.environ['TESTING']


@pytest.fixture
def client(app):
    """Create a test client with authenticated user."""
    client = app.test_client()
    
    # Log in the test user for all tests
    with app.app_context():
        from app import User, login_user
        test_user = User.query.first()
        
        with client.session_transaction() as sess:
            # Manually set the user ID in the session to simulate login
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
    
    return client


@pytest.fixture
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def sample_data(app):
    """Create sample data for tests."""
    with app.app_context():
        from app import db, Territory, Seller, Customer, Topic, CallLog, User
        
        # Get the test user
        test_user = User.query.first()
        
        # Create territories
        territory1 = Territory(name='West Region', user_id=test_user.id)
        territory2 = Territory(name='East Region', user_id=test_user.id)
        db.session.add_all([territory1, territory2])
        db.session.flush()
        
        # Create sellers
        seller1 = Seller(name='Alice Smith', alias='alices', seller_type='Growth', user_id=test_user.id)
        seller2 = Seller(name='Bob Jones', alias='bobj', seller_type='Acquisition', user_id=test_user.id)
        db.session.add_all([seller1, seller2])
        db.session.flush()
        
        # Associate sellers with territories
        seller1.territories.append(territory1)
        seller2.territories.append(territory2)
        
        # Create customers - Note: tpid is BigInteger so use numbers
        customer1 = Customer(
            name='Acme Corp',
            tpid=1001,  # Numeric TPID
            tpid_url='https://example.com/acme',
            seller_id=seller1.id,
            territory_id=territory1.id,
            user_id=test_user.id
        )
        customer2 = Customer(
            name='Globex Inc',
            tpid=1002,  # Numeric TPID
            seller_id=seller2.id,
            territory_id=territory2.id,
            user_id=test_user.id
        )
        db.session.add_all([customer1, customer2])
        db.session.flush()
        
        # Create topics
        topic1 = Topic(name='Azure VM', description='Virtual Machines', user_id=test_user.id)
        topic2 = Topic(name='Storage', description='Azure Storage', user_id=test_user.id)
        db.session.add_all([topic1, topic2])
        db.session.flush()
        
        # Create call logs - Use correct field name 'content'
        # Note: seller and territory are now derived from customer relationship
        call1 = CallLog(
            customer_id=customer1.id,
            call_date=datetime.now(timezone.utc),
            content='Discussed VM migration strategy and cloud architecture options.',
            user_id=test_user.id
        )
        call1.topics.append(topic1)
        
        call2 = CallLog(
            customer_id=customer2.id,
            call_date=datetime.now(timezone.utc),
            content='Storage optimization review with focus on blob storage.',
            user_id=test_user.id
        )
        call2.topics.append(topic2)
        
        db.session.add_all([call1, call2])
        db.session.commit()
        
        # Return IDs for use in tests
        return {
            'territory1_id': territory1.id,
            'territory2_id': territory2.id,
            'seller1_id': seller1.id,
            'seller2_id': seller2.id,
            'customer1_id': customer1.id,
            'customer2_id': customer2.id,
            'topic1_id': topic1.id,
            'topic2_id': topic2.id,
            'call1_id': call1.id,
            'call2_id': call2.id,
        }


@pytest.fixture(autouse=True)
def reset_db(app):
    """Reset database between tests."""
    with app.app_context():
        from app import db, UserPreference
        
        # SAFETY CHECK: Ensure we're using SQLite for tests
        db_uri = str(db.engine.url)
        if 'sqlite' not in db_uri.lower():
            raise RuntimeError(
                f"CRITICAL: Tests attempted to run against non-SQLite database: {db_uri}\n"
                f"This could destroy production data! Tests must only use SQLite."
            )
        
        # Drop and recreate all tables for clean slate
        db.drop_all()
        db.create_all()
        
        # Recreate test user and preferences
        from app import User
        test_user = User(
            microsoft_azure_id='test-user-12345',
            email='test@microsoft.com',
            name='Test User'
        )
        db.session.add(test_user)
        db.session.flush()
        
        pref = UserPreference(user_id=test_user.id, dark_mode=False, customer_view_grouped=False, topic_sort_by_calls=False, territory_view_accounts=False)
        db.session.add(pref)
        db.session.commit()
    
    yield
