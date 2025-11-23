"""
Tests for view routes (pages that display data).
These tests verify that pages load correctly and handle eager-loaded relationships.
"""
import pytest


def test_home_page_loads(client):
    """Test that home page loads successfully."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'Welcome to NoteHelper' in response.data


def test_home_page_with_data(client, sample_data):
    """Test home page displays recent calls."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'Recent Call Logs' in response.data
    assert b'Acme Corp' in response.data


def test_customers_list_alphabetical(client, sample_data):
    """Test customers list in alphabetical view."""
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Acme Corp' in response.data
    assert b'Globex Inc' in response.data


def test_customers_list_grouped(client, sample_data):
    """Test customers list in grouped view."""
    # Set preference to grouped
    client.post('/api/preferences/customer-view', 
                json={'customer_view_grouped': True})
    
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Alice Smith' in response.data  # Seller name
    assert b'Acme Corp' in response.data


def test_customer_view_loads(client, sample_data):
    """Test individual customer page loads with eager-loaded data."""
    customer_id = sample_data['customer1_id']
    response = client.get(f'/customer/{customer_id}')
    assert response.status_code == 200
    assert b'Acme Corp' in response.data
    assert b'1001' in response.data
    assert b'Alice Smith' in response.data  # Seller badge
    assert b'West Region' in response.data  # Territory badge


def test_seller_view_loads(client, sample_data):
    """Test seller page loads with sorted customers."""
    seller_id = sample_data['seller1_id']
    response = client.get(f'/seller/{seller_id}')
    assert response.status_code == 200
    assert b'Alice Smith' in response.data
    assert b'Acme Corp' in response.data


def test_seller_view_with_territories(client, sample_data):
    """Test seller page displays territories correctly."""
    seller_id = sample_data['seller1_id']
    response = client.get(f'/seller/{seller_id}')
    assert response.status_code == 200
    assert b'West Region' in response.data


def test_territory_view_loads(client, sample_data):
    """Test territory page loads with sorted sellers (recent calls view)."""
    territory_id = sample_data['territory1_id']
    response = client.get(f'/territory/{territory_id}')
    assert response.status_code == 200
    assert b'West Region' in response.data
    assert b'Alice Smith' in response.data
    assert b'Recent Calls' in response.data


def test_territory_view_accounts(client, sample_data, app):
    """Test territory page loads with accounts view grouped by seller type."""
    from app.models import db, UserPreference
    
    with app.app_context():
        # Set preference to show accounts view
        pref = UserPreference.query.filter_by(user_id=1).first()
        pref.territory_view_accounts = True
        db.session.commit()
    
    territory_id = sample_data['territory1_id']
    response = client.get(f'/territory/{territory_id}')
    assert response.status_code == 200
    assert b'West Region' in response.data
    assert b'Accounts in Territory' in response.data
    assert b'Acme Corp' in response.data


def test_topic_view_loads(client, sample_data):
    """Test topic page loads with sorted call logs."""
    topic_id = sample_data['topic1_id']
    response = client.get(f'/topic/{topic_id}')
    assert response.status_code == 200
    assert b'Azure VM' in response.data
    assert b'Acme Corp' in response.data  # Customer name
    assert b'Discussed VM migration' in response.data


def test_topics_list_alphabetical(client, sample_data):
    """Test topics list sorted alphabetically."""
    response = client.get('/topics')
    assert response.status_code == 200
    assert b'Azure VM' in response.data
    assert b'Storage' in response.data


def test_topics_list_by_calls(client, sample_data):
    """Test topics list sorted by call count."""
    # Set preference to sort by calls
    client.post('/api/preferences/topic-sort',
                json={'topic_sort_by_calls': True})
    
    response = client.get('/topics')
    assert response.status_code == 200
    assert b'Azure VM' in response.data


def test_territories_list_loads(client, sample_data):
    """Test territories list page."""
    response = client.get('/territories')
    assert response.status_code == 200
    assert b'West Region' in response.data
    assert b'East Region' in response.data
    assert b'Alice Smith' in response.data  # Seller badge


def test_sellers_list_loads(client, sample_data):
    """Test sellers list page."""
    response = client.get('/sellers')
    assert response.status_code == 200
    assert b'Alice Smith' in response.data
    assert b'Bob Jones' in response.data


def test_call_logs_list_loads(client, sample_data):
    """Test call logs list page."""
    response = client.get('/call-logs')
    assert response.status_code == 200
    assert b'Acme Corp' in response.data
    assert b'Discussed VM migration' in response.data


def test_call_log_view_loads(client, sample_data):
    """Test individual call log page."""
    call_id = sample_data['call1_id']
    response = client.get(f'/call-log/{call_id}')
    assert response.status_code == 200
    assert b'Acme Corp' in response.data
    assert b'Azure VM' in response.data


def test_search_page_loads(client):
    """Test search page loads."""
    response = client.get('/search')
    assert response.status_code == 200
    assert b'Search Call Logs' in response.data


def test_search_with_query(client, sample_data):
    """Test search with query parameter."""
    response = client.get('/search?q=migration')
    assert response.status_code == 200
    assert b'Discussed VM migration' in response.data or b'Search Results' in response.data


def test_preferences_page_loads(client):
    """Test preferences page loads."""
    response = client.get('/preferences')
    assert response.status_code == 200
    assert b'Settings' in response.data


def test_customers_list_filters_without_calls(client, sample_data):
    """Test that customers without calls are filtered when preference is False."""
    from app.models import Customer, db
    
    # Create a customer without any call logs
    customer = Customer(
        name='Empty Customer',
        tpid=9999,
        user_id=1
    )
    db.session.add(customer)
    db.session.commit()
    
    # Default preference is False (hide customers without calls)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Empty Customer' not in response.data
    
    # Enable showing customers without calls
    client.post('/api/preferences/show-customers-without-calls',
                json={'show_customers_without_calls': True})
    
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Empty Customer' in response.data
    assert b'Dark Mode' in response.data
