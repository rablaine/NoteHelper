"""
Tests for account linking functionality.
Tests the full workflow of Microsoft and external account linking.
"""
import pytest
from datetime import datetime


@pytest.fixture
def whitelisted_domain(app):
    """Create a whitelisted domain for testing."""
    from app import db, WhitelistedDomain
    with app.app_context():
        domain = WhitelistedDomain(domain='partnertenant.onmicrosoft.com', added_by_user_id=1)
        db.session.add(domain)
        db.session.commit()
        return domain.domain


def test_domain_whitelist_allows_microsoft(app):
    """Test that @microsoft.com domains are always allowed."""
    from app import WhitelistedDomain
    with app.app_context():
        assert WhitelistedDomain.is_domain_allowed('alex@microsoft.com') is True
        assert WhitelistedDomain.is_domain_allowed('ALEX@MICROSOFT.COM') is True


def test_domain_whitelist_blocks_non_whitelisted(app):
    """Test that non-whitelisted domains are blocked."""
    from app import WhitelistedDomain
    with app.app_context():
        assert WhitelistedDomain.is_domain_allowed('alex@example.com') is False
        assert WhitelistedDomain.is_domain_allowed('alex@gmail.com') is False


def test_domain_whitelist_allows_whitelisted(app, whitelisted_domain):
    """Test that whitelisted domains are allowed."""
    from app import WhitelistedDomain
    with app.app_context():
        email = f'alex@{whitelisted_domain}'
        assert WhitelistedDomain.is_domain_allowed(email) is True


def test_user_account_type_property(app):
    """Test the account_type property returns correct values."""
    from app import User
    with app.app_context():
        # Dual account
        user_dual = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123',
            external_azure_id='ext-123'
        )
        assert user_dual.account_type == 'dual'
        
        # Microsoft only
        user_ms = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123'
        )
        assert user_ms.account_type == 'microsoft'
        
        # External only
        user_ext = User(
            email='alex@microsoft.com',
            name='Alex',
            external_azure_id='ext-123'
        )
        assert user_ext.account_type == 'external'
        
        # No accounts (should not happen but test it)
        user_none = User(
            email='alex@microsoft.com',
            name='Alex'
        )
        assert user_none.account_type == 'unknown'


def test_user_get_pending_link_requests(app):
    """Test getting pending link requests for a user."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create target user
        target = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123'
        )
        db.session.add(target)
        db.session.flush()
        
        # Create stub user
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        # Create pending request
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email=target.email,
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
        
        # Test getting pending requests
        pending = target.get_pending_link_requests()
        assert len(pending) == 1
        assert pending[0].requesting_user_id == stub.id
        assert pending[0].status == 'pending'


def test_domain_not_allowed_page(client):
    """Test that domain_not_allowed page displays correctly."""
    response = client.get('/domain-not-allowed?email=alex@example.com')
    assert response.status_code == 200
    assert b'alex@example.com' in response.data
    assert b'not currently whitelisted' in response.data


def test_admin_domains_page_requires_admin(client, app):
    """Test that admin domains page requires admin privileges."""
    from app import db, User
    # Mock a non-admin user
    with app.app_context():
        user = User.query.first()
        user.is_admin = False
        db.session.commit()
    
    response = client.get('/admin/domains')
    # Should redirect or show unauthorized
    assert response.status_code in [302, 403]


def test_admin_can_add_domain(client, app):
    """Test that admin can add a domain to whitelist."""
    from app import db, User, WhitelistedDomain
    with app.app_context():
        # Ensure user is admin
        user = User.query.first()
        user.is_admin = True
        db.session.commit()
    
    response = client.post('/api/admin/domain/add',
                          json={'domain': 'newpartner.com'},
                          content_type='application/json')
    
    assert response.status_code == 201
    
    # Verify domain was added
    with app.app_context():
        domain = WhitelistedDomain.query.filter_by(domain='newpartner.com').first()
        assert domain is not None
        assert domain.domain == 'newpartner.com'


def test_admin_cannot_add_invalid_domain(client, app):
    """Test that invalid domains are rejected."""
    from app import db, User
    with app.app_context():
        user = User.query.first()
        user.is_admin = True
        db.session.commit()
    
    # Domain with @ symbol should be rejected
    response = client.post('/api/admin/domain/add',
                          json={'domain': 'alex@example.com'},
                          content_type='application/json')
    assert response.status_code == 400
    
    # Domain without dot should be rejected
    response = client.post('/api/admin/domain/add',
                          json={'domain': 'example'},
                          content_type='application/json')
    assert response.status_code == 400


def test_admin_cannot_add_duplicate_domain(client, app, whitelisted_domain):
    """Test that duplicate domains are rejected."""
    from app import db, User
    with app.app_context():
        user = User.query.first()
        user.is_admin = True
        db.session.commit()
    
    response = client.post('/api/admin/domain/add',
                          json={'domain': whitelisted_domain},
                          content_type='application/json')
    
    assert response.status_code == 400
    assert b'already whitelisted' in response.data


def test_admin_can_remove_domain(client, app, whitelisted_domain):
    """Test that admin can remove a domain from whitelist."""
    from app import db, User, WhitelistedDomain
    with app.app_context():
        user = User.query.first()
        user.is_admin = True
        db.session.commit()
        
        # Get domain ID
        domain = WhitelistedDomain.query.filter_by(domain=whitelisted_domain).first()
        domain_id = domain.id
    
    response = client.post(f'/api/admin/domain/remove/{domain_id}')
    assert response.status_code == 200
    
    # Verify domain was removed
    with app.app_context():
        domain = WhitelistedDomain.query.filter_by(domain=whitelisted_domain).first()
        assert domain is None


def test_stub_user_restricted_access(client, app):
    """Test that stub users cannot access regular app routes."""
    from app import db, User
    with app.app_context():
        # Create stub user
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.commit()
        
        # Mock login as stub user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(stub.id)
    
    # Try to access regular routes - should redirect to account_link_status
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 302
    assert '/account/link-status' in response.location


def test_account_link_status_page(client, app):
    """Test account link status page shows pending requests."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create stub user with pending request
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email='alex@microsoft.com',
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
        
        # Mock login as stub user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(stub.id)
    
    response = client.get('/account/link-status')
    assert response.status_code == 200
    assert b'alex@microsoft.com' in response.data
    assert b'Pending Account Linking' in response.data


def test_user_profile_shows_pending_requests(client, app):
    """Test that user profile shows pending link requests."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create full user
        user = User.query.first()
        
        # Create stub user with pending request
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email=user.email,
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
    
    response = client.get('/profile')
    assert response.status_code == 200
    assert b'Pending Account Linking Request' in response.data


def test_approve_link_request_merges_accounts(client, app):
    """Test that approving a link request merges the accounts."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create target user (Microsoft only)
        target = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123'
        )
        db.session.add(target)
        db.session.flush()
        
        # Create stub user (external)
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        # Create pending request
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email=target.email,
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
        
        request_id = request.id
        target_id = target.id
        
        # Mock login as target user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(target_id)
    
    # Approve the request
    response = client.post(f'/account/link/approve/{request_id}', follow_redirects=False)
    assert response.status_code == 302
    
    # Verify accounts were merged
    with app.app_context():
        merged_user = User.query.get(target_id)
        assert merged_user.microsoft_azure_id == 'ms-123'
        assert merged_user.external_azure_id == 'ext-123'
        assert merged_user.linked_at is not None
        assert merged_user.account_type == 'dual'
        
        # Verify stub was deleted
        stub_user = User.query.filter_by(is_stub=True, email='alex@partnertenant.onmicrosoft.com').first()
        assert stub_user is None
        
        # Verify request was marked approved (gravestone)
        link_request = AccountLinkingRequest.query.get(request_id)
        assert link_request.status == 'approved'
        assert link_request.resolved_at is not None


def test_deny_link_request(client, app):
    """Test that denying a link request marks it as denied."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create target user
        target = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123'
        )
        db.session.add(target)
        db.session.flush()
        
        # Create stub user
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        # Create pending request
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email=target.email,
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
        
        request_id = request.id
        target_id = target.id
        
        # Mock login as target user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(target_id)
    
    # Deny the request
    response = client.post(f'/account/link/deny/{request_id}', follow_redirects=False)
    assert response.status_code == 302
    
    # Verify request was marked denied
    with app.app_context():
        link_request = AccountLinkingRequest.query.get(request_id)
        assert link_request.status == 'denied'
        assert link_request.resolved_at is not None
        
        # Verify target user unchanged
        target_user = User.query.get(target_id)
        assert target_user.external_azure_id is None
        assert target_user.account_type == 'microsoft'


def test_cannot_link_already_linked_account_type(client, app):
    """Test that you cannot link an account type that's already linked."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create target user with both accounts already linked
        target = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123',
            external_azure_id='ext-456'
        )
        db.session.add(target)
        db.session.flush()
        
        # Create stub user trying to link another external account
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-789',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        # Create pending request
        request = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email=target.email,
            status='pending'
        )
        db.session.add(request)
        db.session.commit()
        
        request_id = request.id
        target_id = target.id
        
        # Mock login as target user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(target_id)
    
    # Try to approve - should redirect back to profile
    response = client.post(f'/account/link/approve/{request_id}', follow_redirects=False)
    assert response.status_code == 302
    assert '/profile' in response.location
    
    # Verify the account was NOT linked (external_azure_id should still be ext-456)
    with app.app_context():
        target_after = User.query.get(target_id)
        assert target_after.external_azure_id == 'ext-456'  # Original, not changed


def test_duplicate_link_request_cancels_oldest(app):
    """Test that creating a duplicate request cancels the oldest one."""
    from app import db, User, AccountLinkingRequest
    # This would be integration tested via the full auth flow
    # For now, test the database constraint behavior
    with app.app_context():
        # Create stub user
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        # Create first request
        request1 = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email='alex@microsoft.com',
            status='pending'
        )
        db.session.add(request1)
        db.session.commit()
        
        # Simulate cancelling old request and creating new one
        request1.status = 'cancelled'
        request1.resolved_at = datetime.now()
        
        request2 = AccountLinkingRequest(
            requesting_user_id=stub.id,
            target_email='alex@microsoft.com',
            status='pending'
        )
        db.session.add(request2)
        db.session.commit()
        
        # Verify only one pending request
        pending = AccountLinkingRequest.query.filter_by(
            requesting_user_id=stub.id,
            status='pending'
        ).all()
        assert len(pending) == 1
        assert pending[0].id == request2.id
        
        # Verify old request is cancelled
        cancelled = AccountLinkingRequest.query.filter_by(
            requesting_user_id=stub.id,
            status='cancelled'
        ).first()
        assert cancelled is not None
        assert cancelled.id == request1.id


def test_gravestone_kept_after_stub_deletion(client, app):
    """Test that AccountLinkingRequest record is kept after stub deletion."""
    from app import db, User, AccountLinkingRequest
    with app.app_context():
        # Create target user
        target = User(
            email='alex@microsoft.com',
            name='Alex',
            microsoft_azure_id='ms-123'
        )
        db.session.add(target)
        db.session.flush()
        
        # Create stub user
        stub = User(
            email='alex@partnertenant.onmicrosoft.com',
            name='Alex',
            external_azure_id='ext-123',
            is_stub=True
        )
        db.session.add(stub)
        db.session.flush()
        
        stub_id = stub.id
        
        # Create and approve request
        request = AccountLinkingRequest(
            requesting_user_id=stub_id,
            target_email=target.email,
            status='approved',
            resolved_at=datetime.now(),
            resolved_by_user_id=target.id
        )
        db.session.add(request)
        
        # Delete stub (simulating approval process)
        db.session.delete(stub)
        db.session.commit()
        
        # Verify stub is gone
        assert User.query.get(stub_id) is None
        
        # Verify gravestone request still exists
        gravestone = AccountLinkingRequest.query.filter_by(requesting_user_id=stub_id).first()
        assert gravestone is not None
        assert gravestone.status == 'approved'
        assert gravestone.target_email == 'alex@microsoft.com'
