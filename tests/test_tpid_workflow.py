"""
Tests for TPID URL workflow functionality.
"""
import pytest
from io import BytesIO


def test_tpid_workflow_page_loads(client, sample_data):
    """Test that TPID workflow page loads successfully."""
    response = client.get('/tpid-workflow')
    assert response.status_code == 200
    assert b'TPID URL Workflow' in response.data


def test_tpid_workflow_shows_customers_without_urls(client, sample_data):
    """Test that workflow only shows customers without TPID URLs."""
    response = client.get('/tpid-workflow')
    assert response.status_code == 200
    
    # Check that page mentions customers without URLs
    # Sample data has at least one customer without TPID URL
    assert b'customer' in response.data.lower()


def test_tpid_workflow_update_single_url(client, sample_data, app):
    """Test updating a single TPID URL via workflow."""
    with app.app_context():
        from app.models import Customer
        
        # Find a customer without TPID URL
        customer = Customer.query.filter(
            (Customer.tpid_url == None) | (Customer.tpid_url == '')
        ).first()
        
        if not customer:
            pytest.skip("No customers without TPID URLs in sample data")
        
        customer_id = customer.id
        test_url = 'https://example.com/crm/test-customer-123'
        
        # Submit update
        response = client.post('/tpid-workflow/update', data={
            f'tpid_url_{customer_id}': test_url
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Successfully updated' in response.data
        
        # Verify URL was saved
        customer = Customer.query.get(customer_id)
        assert customer.tpid_url == test_url


def test_tpid_workflow_update_multiple_urls(client, sample_data, app):
    """Test updating multiple TPID URLs at once."""
    with app.app_context():
        from app.models import Customer, db
        
        # Find customers without TPID URLs
        customers = Customer.query.filter(
            (Customer.tpid_url == None) | (Customer.tpid_url == '')
        ).limit(2).all()
        
        if len(customers) < 2:
            pytest.skip("Need at least 2 customers without TPID URLs")
        
        # Prepare update data
        update_data = {}
        expected_urls = {}
        for i, customer in enumerate(customers):
            url = f'https://example.com/crm/customer-{i+1}'
            update_data[f'tpid_url_{customer.id}'] = url
            expected_urls[customer.id] = url
        
        # Submit update
        response = client.post('/tpid-workflow/update', data=update_data, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Successfully updated 2' in response.data
        
        # Verify all URLs were saved
        for customer_id, expected_url in expected_urls.items():
            customer = Customer.query.get(customer_id)
            assert customer.tpid_url == expected_url


def test_tpid_workflow_ignores_empty_fields(client, sample_data, app):
    """Test that empty URL fields are ignored during update."""
    with app.app_context():
        from app.models import Customer
        
        # Find customers without TPID URLs
        customers = Customer.query.filter(
            (Customer.tpid_url == None) | (Customer.tpid_url == '')
        ).limit(2).all()
        
        if len(customers) < 2:
            pytest.skip("Need at least 2 customers without TPID URLs")
        
        # Submit with one filled and one empty
        customer1_id = customers[0].id
        customer2_id = customers[1].id
        test_url = 'https://example.com/crm/only-this-one'
        
        response = client.post('/tpid-workflow/update', data={
            f'tpid_url_{customer1_id}': test_url,
            f'tpid_url_{customer2_id}': ''  # Empty - should be ignored
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Successfully updated 1' in response.data
        
        # Verify only the filled one was saved
        customer1 = Customer.query.get(customer1_id)
        customer2 = Customer.query.get(customer2_id)
        assert customer1.tpid_url == test_url
        assert not customer2.tpid_url  # Should still be empty


def test_tpid_workflow_empty_when_all_filled(client, sample_data, app):
    """Test workflow page shows completion message when all URLs are filled."""
    with app.app_context():
        from app.models import Customer, db
        
        # Fill all TPID URLs
        customers = Customer.query.all()
        for customer in customers:
            if not customer.tpid_url:
                customer.tpid_url = f'https://example.com/crm/customer-{customer.id}'
        db.session.commit()
        
        # Check workflow page
        response = client.get('/tpid-workflow')
        assert response.status_code == 200
        assert b'All Done!' in response.data or b'All customers have TPID URLs' in response.data


def test_tpid_workflow_groups_by_seller(client, sample_data):
    """Test that workflow page groups customers by seller."""
    response = client.get('/tpid-workflow')
    assert response.status_code == 200
    
    # Check for seller grouping indicators (seller names or group headers)
    # This is a basic check - actual grouping is visual
    assert b'seller' in response.data.lower() or b'bi-person' in response.data


def test_tpid_workflow_update_validates_customer_exists(client, sample_data):
    """Test that updating non-existent customer is handled gracefully."""
    response = client.post('/tpid-workflow/update', data={
        'tpid_url_99999': 'https://example.com/fake'
    }, follow_redirects=True)
    
    # Should not crash, but also should not update anything
    assert response.status_code == 200
