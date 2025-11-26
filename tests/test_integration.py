"""
Integration tests that POST to create endpoints.
These tests verify that all model creations properly set user_id.
"""
import pytest
from datetime import date
from app.models import db, CallLog, Customer, Seller, Territory, Topic


def test_call_log_create_post_sets_user_id(client, sample_data):
    """Test that posting to call log create properly sets user_id."""
    customer_id = sample_data['customer1_id']
    
    response = client.post('/call-log/new', data={
        'customer_id': customer_id,
        'call_date': date.today().strftime('%Y-%m-%d'),
        'content': '<p>Test call log content</p>',
        'topic_ids': []
    }, follow_redirects=False)
    
    # Should redirect to view page
    assert response.status_code == 302
    
    # Verify call log was created with user_id
    call_log = CallLog.query.filter_by(customer_id=customer_id).order_by(CallLog.id.desc()).first()
    assert call_log is not None
    assert call_log.user_id is not None
    assert call_log.user_id == 1  # Test user ID
    assert call_log.content == '<p>Test call log content</p>'


def test_customer_create_post_sets_user_id(client, sample_data):
    """Test that posting to customer create properly sets user_id."""
    seller_id = sample_data['seller1_id']
    
    response = client.post('/customer/new', data={
        'name': 'Test Customer Integration',
        'nickname': '',
        'tpid': '999999',
        'tpid_url': '',
        'seller_id': seller_id,
        'territory_id': ''
    }, follow_redirects=False)
    
    # Should redirect
    assert response.status_code == 302
    
    # Verify customer was created with user_id
    customer = Customer.query.filter_by(tpid=999999).first()
    assert customer is not None
    assert customer.user_id is not None
    assert customer.user_id == 1
    assert customer.name == 'Test Customer Integration'


def test_seller_create_post_sets_user_id(client, sample_data):
    """Test that posting to seller create properly sets user_id."""
    response = client.post('/seller/new', data={
        'name': 'Test Seller Integration',
        'territory_ids': []
    }, follow_redirects=False)
    
    # Should redirect
    assert response.status_code == 302
    
    # Verify seller was created with user_id
    seller = Seller.query.filter_by(name='Test Seller Integration').first()
    assert seller is not None
    assert seller.user_id is not None
    assert seller.user_id == 1


def test_territory_create_post_sets_user_id(client, sample_data):
    """Test that posting to territory create properly sets user_id."""
    response = client.post('/territory/new', data={
        'name': 'Test Territory Integration',
        'pod_id': ''
    }, follow_redirects=False)
    
    # Should redirect
    assert response.status_code == 302
    
    # Verify territory was created with user_id
    territory = Territory.query.filter_by(name='Test Territory Integration').first()
    assert territory is not None
    assert territory.user_id is not None
    assert territory.user_id == 1


def test_topic_create_post_sets_user_id(client, sample_data):
    """Test that posting to topic create properly sets user_id."""
    response = client.post('/topic/new', data={
        'name': 'Test Topic Integration',
        'description': 'Test description'
    }, follow_redirects=False)
    
    # Should redirect
    assert response.status_code == 302
    
    # Verify topic was created with user_id
    topic = Topic.query.filter_by(name='Test Topic Integration').first()
    assert topic is not None
    assert topic.user_id is not None
    assert topic.user_id == 1
    assert topic.description == 'Test description'


def test_call_log_create_without_user_id_fails(client, sample_data):
    """
    Test that demonstrates the bug we fixed.
    If user_id is not set, database should reject with NOT NULL constraint.
    This test validates that our fix prevents the error.
    """
    customer_id = sample_data['customer1_id']
    
    # This should work now (with our fix)
    response = client.post('/call-log/new', data={
        'customer_id': customer_id,
        'call_date': date.today().strftime('%Y-%m-%d'),
        'content': '<p>Should work with user_id set</p>',
        'topic_ids': []
    }, follow_redirects=False)
    
    # Should succeed (not 500 error)
    assert response.status_code == 302
    
    # Verify call log exists and has user_id
    call_log = CallLog.query.filter_by(customer_id=customer_id).order_by(CallLog.id.desc()).first()
    assert call_log is not None
    assert call_log.user_id is not None, "user_id must be set to prevent NOT NULL constraint error"
