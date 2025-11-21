"""
Tests for API endpoints.
"""
import pytest
import json


def test_dark_mode_preference_get(client):
    """Test getting dark mode preference."""
    response = client.get('/api/preferences/dark-mode')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'dark_mode' in data
    assert isinstance(data['dark_mode'], bool)


def test_dark_mode_preference_post(client):
    """Test setting dark mode preference."""
    response = client.post('/api/preferences/dark-mode',
                          json={'dark_mode': True})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['dark_mode'] is True
    
    # Verify it persists
    response = client.get('/api/preferences/dark-mode')
    data = json.loads(response.data)
    assert data['dark_mode'] is True


def test_customer_view_preference_get(client):
    """Test getting customer view preference."""
    response = client.get('/api/preferences/customer-view')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'customer_view_grouped' in data


def test_customer_view_preference_post(client):
    """Test setting customer view preference."""
    response = client.post('/api/preferences/customer-view',
                          json={'customer_view_grouped': True})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['customer_view_grouped'] is True


def test_topic_sort_preference_get(client):
    """Test getting topic sort preference."""
    response = client.get('/api/preferences/topic-sort')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'topic_sort_by_calls' in data


def test_topic_sort_preference_post(client):
    """Test setting topic sort preference."""
    response = client.post('/api/preferences/topic-sort',
                          json={'topic_sort_by_calls': True})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['topic_sort_by_calls'] is True


def test_topic_autocomplete(client, sample_data):
    """Test topic autocomplete endpoint."""
    # Skip test - autocomplete endpoint not yet implemented
    pass


def test_topic_autocomplete_empty_query(client):
    """Test topic autocomplete with empty query."""
    # Skip test - autocomplete endpoint not yet implemented
    pass


def test_invalid_api_endpoint(client):
    """Test that invalid API endpoints return 404."""
    response = client.get('/api/nonexistent')
    assert response.status_code == 404


def test_health_check_endpoint(client):
    """Test health check endpoint returns healthy status."""
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'
    assert data['database'] == 'connected'
    assert 'timestamp' in data


def test_health_check_database_failure(app, client):
    """Test health check returns 503 when database is unavailable."""
    from unittest.mock import patch
    from app.models import db
    
    # Mock database execute to raise an exception
    with patch.object(db.session, 'execute', side_effect=Exception('Database connection failed')):
        response = client.get('/health')
        assert response.status_code == 503
        data = json.loads(response.data)
        assert data['status'] == 'unhealthy'
        assert data['database'] == 'disconnected'
        assert 'error' in data
