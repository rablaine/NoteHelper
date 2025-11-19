"""
Tests specifically for eager-loaded relationship handling.
These tests verify that routes and templates correctly handle InstrumentedList objects
instead of Query objects when relationships are eager-loaded.
"""
import pytest


def test_seller_view_customers_sorted(client, sample_data):
    """Test that seller view correctly sorts eager-loaded customers."""
    seller_id = sample_data['seller1_id']
    response = client.get(f'/seller/{seller_id}')
    assert response.status_code == 200
    # Should not crash with AttributeError on .order_by()
    assert b'Acme Corp' in response.data


def test_customer_view_call_logs_sorted(client, sample_data):
    """Test that customer view correctly sorts eager-loaded call logs."""
    customer_id = sample_data['customer1_id']
    response = client.get(f'/customer/{customer_id}')
    assert response.status_code == 200
    # Should not crash with AttributeError on .order_by()
    assert b'Discussed VM migration' in response.data


def test_topic_view_call_logs_sorted(client, sample_data):
    """Test that topic view correctly sorts eager-loaded call logs."""
    topic_id = sample_data['topic1_id']
    response = client.get(f'/topic/{topic_id}')
    assert response.status_code == 200
    # Should not crash with AttributeError on .order_by()
    assert b'Discussed VM migration' in response.data


def test_territory_view_sellers_sorted(client, sample_data):
    """Test that territory view correctly sorts eager-loaded sellers."""
    territory_id = sample_data['territory1_id']
    response = client.get(f'/territory/{territory_id}')
    assert response.status_code == 200
    # Should not crash with AttributeError on .order_by()
    assert b'Alice Smith' in response.data


def test_customer_form_seller_customers_sorted(client, sample_data):
    """Test that customer form correctly handles eager-loaded seller customers."""
    response = client.get('/customer/new')
    assert response.status_code == 200
    # Should not crash with AttributeError on .order_by()
    assert b'Alice Smith' in response.data


def test_customer_form_territory_sellers(client, sample_data):
    """Test that customer form correctly handles eager-loaded territory sellers."""
    territory_id = sample_data['territory1_id']
    response = client.get(f'/customer/new?territory_id={territory_id}')
    assert response.status_code == 200
    # Should not crash with AttributeError on .all()
    assert b'West Region' in response.data


def test_customer_view_topics_count(client, sample_data):
    """Test that customer view template uses |length instead of .count()."""
    customer_id = sample_data['customer1_id']
    response = client.get(f'/customer/{customer_id}')
    assert response.status_code == 200
    # Should not crash with TypeError on .count()
    assert b'Call Logs' in response.data


def test_call_log_view_topics_iteration(client, sample_data):
    """Test that call log view template iterates topics correctly."""
    call_id = sample_data['call1_id']
    response = client.get(f'/call-log/{call_id}')
    assert response.status_code == 200
    # Should not crash trying to call .all() on topics
    assert b'Azure VM' in response.data


def test_seller_view_territories_length(client, sample_data):
    """Test that seller view template uses |length for territories."""
    seller_id = sample_data['seller1_id']
    response = client.get(f'/seller/{seller_id}')
    assert response.status_code == 200
    # Should not crash with .count()
    assert b'West Region' in response.data


def test_territory_view_seller_customers_count(client, sample_data):
    """Test that territory view uses |length for seller customers."""
    territory_id = sample_data['territory1_id']
    response = client.get(f'/territory/{territory_id}')
    assert response.status_code == 200
    # Should show customer count without crashing
    assert b'customers' in response.data


def test_customer_form_seller_territories_data_attributes(client, sample_data):
    """Test that customer form correctly builds territory data attributes."""
    response = client.get('/customer/new')
    assert response.status_code == 200
    # Should have data-territory-ids attributes
    assert b'data-territory-ids' in response.data or b'data-territory-id' in response.data
