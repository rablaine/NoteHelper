"""
Tests for AI-powered topic suggestion features.
"""

import json
from datetime import date, datetime
from unittest.mock import patch, MagicMock
import pytest
from app import db
from app.models import AIConfig, AIQueryLog, Topic, User


class TestAIConfig:
    """Test AI configuration management."""
    
    def test_ai_config_defaults(self, app, client):
        """Test default AI config values."""
        with app.app_context():
            # Set test user as admin
            test_user = User.query.first()
            test_user.is_admin = True
            db.session.commit()
        
        response = client.get('/admin')
        assert response.status_code == 200
        
        # Check that default config exists
        config = AIConfig.query.first()
        assert config is not None
        assert config.enabled is False
        assert config.api_version == '2024-08-01-preview'
        assert 'helpful assistant' in config.system_prompt.lower()
    
    def test_update_ai_config(self, app, client):
        """Test updating AI configuration."""
        with app.app_context():
            # Set test user as admin
            test_user = User.query.first()
            test_user.is_admin = True
            db.session.commit()
        
        response = client.post('/api/admin/ai-config', json={
            'enabled': True,
            'endpoint_url': 'https://test.endpoint.com',
            'api_key': 'test-key-123',
            'deployment_name': 'gpt-4',
            'api_version': '2024-08-01-preview',
            'system_prompt': 'Custom prompt'
        })
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        
        # Verify changes persisted
        config = AIConfig.query.first()
        assert config.enabled is True
        assert config.endpoint_url == 'https://test.endpoint.com'
        assert config.api_key == 'test-key-123'
        assert config.deployment_name == 'gpt-4'
        assert config.system_prompt == 'Custom prompt'
    

class TestAIConnection:
    """Test AI connection testing functionality."""
    
    @patch('requests.post')
    def test_connection_test_success(self, mock_post, app, client):
        """Test successful AI connection test."""
        with app.app_context():
            test_user = User.query.first()
            test_user.is_admin = True
            db.session.commit()
        
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'Azure OpenAI, GPT-4, Testing'}}]
        }
        mock_post.return_value = mock_response
        
        response = client.post('/api/admin/ai-config/test', json={
            'endpoint_url': 'https://test.endpoint.com/openai/deployments/gpt-4',
            'api_key': 'test-key',
            'deployment_name': 'gpt-4',
            'api_version': '2024-08-01-preview'
        })
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'successful' in data['message'].lower()
        
        # Verify correct API call was made
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert 'Bearer test-key' in str(call_args)
        assert '/chat/completions' in call_args[0][0]
        assert 'api-version=2024-08-01-preview' in call_args[0][0]
    
    @patch('requests.post')
    def test_connection_test_failure(self, mock_post, app, client):
        """Test failed AI connection test."""
        with app.app_context():
            test_user = User.query.first()
            test_user.is_admin = True
            db.session.commit()
        
        # Mock failed API response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {'error': {'message': 'Unauthorized'}}
        mock_post.return_value = mock_response
        
        response = client.post('/api/admin/ai-config/test', json={
            'endpoint_url': 'https://test.endpoint.com',
            'api_key': 'bad-key',
            'deployment_name': 'gpt-4',
            'api_version': '2024-08-01-preview'
        })
        
        # Should return error response
        data = response.get_json()
        assert data['success'] is False
        error_text = data.get('message', data.get('error', '')).lower()
        assert 'failed' in error_text or 'error' in error_text or '401' in error_text


class TestAISuggestions:
    """Test AI topic suggestion functionality."""
    
    def setup_ai_config(self):
        """Helper to set up enabled AI config."""
        config = AIConfig.query.first()
        if not config:
            config = AIConfig()
            db.session.add(config)
        
        config.enabled = True
        config.endpoint_url = 'https://test.endpoint.com'
        config.api_key = 'test-key'
        config.deployment_name = 'o3-mini'
        config.api_version = '2025-01-01-preview'
        db.session.commit()
        return config
    
    @patch('requests.post')
    def test_suggest_topics_success(self, mock_post, app, client):
        """Test successful topic suggestion."""
        with app.app_context():
            self.setup_ai_config()
            test_user = User.query.first()
        
        # Mock successful API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'choices': [{
                    'message': {
                        'content': '[\"Azure Functions\", \"API Management\", \"Serverless\"]'
                    }
                }]
            }
            mock_post.return_value = mock_response
            
            response = client.post('/api/ai/suggest-topics', json={
                'call_notes': 'Discussed Azure Functions and API Management for serverless architecture'
            })
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True
            assert len(data['topics']) == 3
            assert any('azure functions' in t['name'].lower() for t in data['topics'])
            
            # Verify topics were created
            topics = Topic.query.all()
            assert len(topics) == 3
            
            # Verify audit log entry
            log = AIQueryLog.query.first()
            assert log is not None
            assert log.user_id == test_user.id
            assert log.success is True
            assert 'Azure Functions' in log.request_text
    
    @patch('requests.post')
    def test_suggest_topics_reuses_existing(self, mock_post, app, client):
        """Test that existing topics are reused (case-insensitive)."""
        with app.app_context():
            self.setup_ai_config()
            
            # Create existing topic with different case
            test_user = User.query.first()
            existing_topic = Topic(name='azure functions', user_id=test_user.id)
            db.session.add(existing_topic)
            db.session.commit()
            existing_id = existing_topic.id
            
            # Mock API response with same topic (different case)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'choices': [{
                    'message': {
                        'content': '["Azure Functions", "Cosmos DB"]'
                    }
                }]
            }
            mock_post.return_value = mock_response
            
            response = client.post('/api/ai/suggest-topics', json={
                'call_notes': 'Discussed Azure Functions and Cosmos DB'
            })
            
            assert response.status_code == 200
            data = response.get_json()
            
            # Should return 2 topics (one reused, one new)
            assert len(data['topics']) == 2
            assert any(t['id'] == existing_id for t in data['topics'])
            
            # Total topics in DB should be 2 (not 3)
            assert Topic.query.count() == 2
    
    def test_suggest_topics_when_disabled(self, app, client):
        """Test that suggestions fail when AI is disabled."""
        with app.app_context():
            # Ensure AI is disabled
            config = AIConfig.query.first()
            if config:
                config.enabled = False
                db.session.commit()
        
        response = client.post('/api/ai/suggest-topics', json={
            'call_notes': 'Test content'
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'not enabled' in data['error'].lower() or 'not configured' in data['error'].lower()
    
    def test_suggest_topics_requires_call_notes(self, app, client):
        """Test that call_notes parameter is required."""
        with app.app_context():
            self.setup_ai_config()
        
        response = client.post('/api/ai/suggest-topics', json={})
        
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'too short' in data['error'].lower() or 'required' in data['error'].lower() or 'call notes' in data['error'].lower()


class TestAuditLogging:
    """Test AI audit logging functionality."""
    
    def setup_ai_config(self):
        """Helper to set up enabled AI config."""
        config = AIConfig.query.first()
        if not config:
            config = AIConfig()
            db.session.add(config)
        
        config.enabled = True
        config.endpoint_url = 'https://test.endpoint.com'
        config.api_key = 'test-key'
        config.deployment_name = 'o3-mini'
        db.session.commit()
        return config
    
    @patch('requests.post')
    def test_audit_log_success(self, mock_post, app, client):
        """Test that successful calls are logged."""
        with app.app_context():
            self.setup_ai_config()
            test_user = User.query.first()
            user_id = test_user.id
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'choices': [{'message': {'content': '["Topic1", "Topic2"]'}}]
            }
            mock_post.return_value = mock_response
            
            client.post('/api/ai/suggest-topics', json={
                'call_notes': 'Test content for audit log'
            })
            
            # Check audit log
            log = AIQueryLog.query.first()
            assert log is not None
            assert log.user_id == user_id
            assert log.success is True
            assert 'Test content for audit log' in log.request_text
            assert 'Topic1' in log.response_text and 'Topic2' in log.response_text
            assert log.error_message is None
            assert isinstance(log.timestamp, datetime)
    
    @patch('requests.post')
    def test_audit_log_failure(self, mock_post, app, client):
        """Test that failed calls are logged with error."""
        with app.app_context():
            self.setup_ai_config()
            
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.return_value = {'error': {'message': 'Internal server error'}}
            mock_post.return_value = mock_response
            
            client.post('/api/ai/suggest-topics', json={
                'call_notes': 'This call will fail'
            })
            
            # Check audit log
            log = AIQueryLog.query.first()
            assert log is not None
            assert log.success is False
            assert 'This call will fail' in log.request_text
            assert log.error_message is not None
            # Error message could be parse error or HTTP error
            assert log.error_message is not None and len(log.error_message) > 0
    
    @patch('requests.post')
    def test_audit_log_truncation(self, mock_post, app, client):
        """Test that long texts are truncated in audit log."""
        with app.app_context():
            self.setup_ai_config()
            
            # Create very long call notes (over 1000 chars)
            long_notes = 'A' * 1500
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'choices': [{'message': {'content': 'B' * 1500}}]
            }
            mock_post.return_value = mock_response
            
            client.post('/api/ai/suggest-topics', json={
                'call_notes': long_notes
            })
            
            # Check audit log truncation
            log = AIQueryLog.query.first()
            assert log is not None
            assert len(log.request_text) <= 1000
            assert len(log.response_text) <= 1000



