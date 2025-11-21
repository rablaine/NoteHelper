"""
Admin routes for NoteHelper.
Handles admin panel, user management, and domain whitelisting.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.models import db, User, WhitelistedDomain, POD, Territory, Seller, Customer, Topic, CallLog, AIConfig, utc_now

# Create blueprint
admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
@login_required
def admin_panel():
    """Admin control panel for managing users and system-wide operations."""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('main.index'))
    
    # Get all users
    users = User.query.order_by(User.created_at.desc()).all()
    
    # Get system-wide statistics
    stats = {
        'total_users': User.query.count(),
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
    
    return render_template('admin_panel.html', users=users, stats=stats, ai_config=ai_config)


@admin_bp.route('/admin/domains')
@login_required
def admin_domains():
    """Manage whitelisted domains."""
    if not current_user.is_admin:
        flash('You do not have permission to access domain management.', 'danger')
        return redirect(url_for('main.index'))
    
    domains = WhitelistedDomain.query.order_by(WhitelistedDomain.domain).all()
    return render_template('admin_domains.html', domains=domains)


# API routes
@admin_bp.route('/api/grant-admin/<int:user_id>', methods=['POST'])
@login_required
def api_grant_admin(user_id):
    """Grant admin privileges to a user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'{user.name} is now an admin'})


@admin_bp.route('/api/revoke-admin/<int:user_id>', methods=['POST'])
@login_required
def api_revoke_admin(user_id):
    """Revoke admin privileges from a user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Prevent revoking your own admin
    if user_id == current_user.id:
        return jsonify({'error': 'You cannot revoke your own admin privileges'}), 400
    
    user = User.query.get_or_404(user_id)
    user.is_admin = False
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'{user.name} is no longer an admin'})


@admin_bp.route('/api/admin/domain/add', methods=['POST'])
@login_required
def api_admin_domain_add():
    """Add a domain to the whitelist."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    domain = data.get('domain', '').strip().lower()
    
    if not domain:
        return jsonify({'error': 'Domain is required'}), 400
    
    # Basic validation
    if '@' in domain or not '.' in domain:
        return jsonify({'error': 'Invalid domain format. Enter just the domain (e.g., partner.onmicrosoft.com)'}), 400
    
    # Check if already exists
    existing = WhitelistedDomain.query.filter_by(domain=domain).first()
    if existing:
        return jsonify({'error': f'Domain {domain} is already whitelisted'}), 400
    
    # Add domain
    try:
        new_domain = WhitelistedDomain(domain=domain, added_by_user_id=current_user.id)
        db.session.add(new_domain)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Domain {domain} added to whitelist',
            'domain': {'id': new_domain.id, 'domain': new_domain.domain, 'created_at': new_domain.created_at.isoformat()}
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error adding domain: {str(e)}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500


@admin_bp.route('/api/admin/domain/remove/<int:domain_id>', methods=['POST'])
@login_required
def api_admin_domain_remove(domain_id):
    """Remove a domain from the whitelist."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    domain = WhitelistedDomain.query.get_or_404(domain_id)
    domain_name = domain.domain
    
    db.session.delete(domain)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Domain {domain_name} removed from whitelist'})


# AI Configuration API routes
@admin_bp.route('/api/admin/ai-config', methods=['POST'])
@login_required
def api_admin_ai_config_update():
    """Update AI configuration."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
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
    ai_config.max_daily_calls_per_user = int(data.get('max_daily_calls_per_user', 20))
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'AI configuration updated successfully'})


@admin_bp.route('/api/admin/ai-config/test', methods=['POST'])
@login_required
def api_admin_ai_config_test():
    """Test AI configuration by making a sample API call."""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    ai_config = AIConfig.query.first()
    if not ai_config or not ai_config.enabled:
        return jsonify({'error': 'AI features are not enabled'}), 400
    
    if not ai_config.endpoint_url or not ai_config.api_key or not ai_config.deployment_name:
        return jsonify({'error': 'AI configuration is incomplete'}), 400
    
    try:
        from openai import OpenAI
        
        client = OpenAI(
            base_url=ai_config.endpoint_url,
            api_key=ai_config.api_key
        )
        
        # Make a simple test call
        response = client.chat.completions.create(
            model=ai_config.deployment_name,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Connection successful!' and nothing else."}
            ],
            max_tokens=20
        )
        
        result = response.choices[0].message.content.strip()
        return jsonify({'success': True, 'message': 'Connection successful!', 'response': result})
    
    except Exception as e:
        error_msg = str(e)
        return jsonify({'success': False, 'error': f'Connection failed: {error_msg}'}), 400

