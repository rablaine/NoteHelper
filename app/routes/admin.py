"""
Admin routes for NoteHelper.
Handles admin panel, user management, and domain whitelisting.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g

from app.models import db, User, POD, Territory, Seller, Customer, Topic, CallLog, AIConfig, AIQueryLog, utc_now

# Create blueprint
admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
def admin_panel():
    """Admin control panel for system-wide operations."""
    # Get system-wide statistics
    stats = {
        'total_pods': POD.query.count(),
        'total_territories': Territory.query.count(),
        'total_sellers': Seller.query.count(),
        'total_customers': Customer.query.count(),
        'total_topics': Topic.query.count(),
        'total_call_logs': CallLog.query.count()
    }
    
    # Get or create AI config
    ai_config = AIConfig.query.first()
    if not ai_config:
        ai_config = AIConfig()
        db.session.add(ai_config)
        db.session.commit()
    
    return render_template('admin_panel.html', stats=stats, ai_config=ai_config)


@admin_bp.route('/admin/ai-logs')
def admin_ai_logs():
    """View AI query logs for debugging."""
    # Get recent logs (last 50) with users loaded separately
    logs = AIQueryLog.query.order_by(AIQueryLog.timestamp.desc()).limit(50).all()
    
    # Load users for all logs
    user_ids = {log.user_id for log in logs}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}
    
    # Attach users to logs
    for log in logs:
        log.user = users.get(log.user_id)
    
    return render_template('admin_ai_logs.html', logs=logs)


# API routes
@admin_bp.route('/api/admin/domain/add', methods=['POST'])
@admin_bp.route('/api/admin/ai-config', methods=['POST'])
def api_admin_ai_config_update():
    """Update AI configuration."""
    data = request.get_json()
    
    # Get or create AI config
    ai_config = AIConfig.query.first()
    if not ai_config:
        ai_config = AIConfig()
        db.session.add(ai_config)
    
    # Update fields
    ai_config.enabled = data.get('enabled', False)
    ai_config.endpoint_url = data.get('endpoint_url', '').strip() or None
    ai_config.api_key = data.get('api_key', '').strip() or None
    ai_config.deployment_name = data.get('deployment_name', '').strip() or None
    ai_config.api_version = data.get('api_version', '2024-08-01-preview').strip()
    ai_config.system_prompt = data.get('system_prompt', '').strip() or ai_config.system_prompt
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'AI configuration updated successfully'})


@admin_bp.route('/api/admin/ai-config/test', methods=['POST'])
def api_admin_ai_config_test():
    """Test AI configuration by making a sample API call using Entra ID auth."""
    import os
    from openai import AzureOpenAI
    from azure.identity import ClientSecretCredential, get_bearer_token_provider
    
    # Get current form values from request instead of database
    data = request.get_json() or {}
    endpoint_url = data.get('endpoint_url', '').strip()
    deployment_name = data.get('deployment_name', '').strip()
    api_version = data.get('api_version', '2024-12-01-preview').strip()
    
    # Validate required fields
    if not endpoint_url or not deployment_name:
        return jsonify({'error': 'Please fill in endpoint URL and deployment name before testing'}), 400
    
    # Check for service principal credentials in environment
    client_id = os.environ.get('AZURE_CLIENT_ID')
    client_secret = os.environ.get('AZURE_CLIENT_SECRET')
    tenant_id = os.environ.get('AZURE_TENANT_ID')
    
    if not all([client_id, client_secret, tenant_id]):
        return jsonify({'error': 'Missing Azure service principal environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)'}), 400
    
    try:
        # Create credential and token provider
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        token_provider = get_bearer_token_provider(
            credential, 
            "https://cognitiveservices.azure.com/.default"
        )
        
        # Create Azure OpenAI client
        client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint_url,
            azure_ad_token_provider=token_provider,
        )
        
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Connection successful!' and nothing else."}
            ],
            max_tokens=20,
            model=deployment_name
        )
        
        result = response.choices[0].message.content.strip()
        return jsonify({'success': True, 'message': 'Connection successful!', 'response': result})
    
    except Exception as e:
        error_msg = str(e)
        return jsonify({'success': False, 'error': f'Connection failed: {error_msg}'}), 400

