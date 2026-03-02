"""
Admin routes for NoteHelper.
Handles admin panel, user management, and domain whitelisting.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g

from app.models import (
    db, User, POD, Territory, Seller, Customer, Topic, CallLog, AIQueryLog,
    RevenueImport, CustomerRevenueData, ProductRevenueData, RevenueAnalysis,
    RevenueConfig, RevenueEngagement, Milestone, Opportunity, MsxTask,
    SyncStatus, UserPreference, call_logs_milestones, utc_now
)

# Create blueprint
admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
def admin_panel():
    """Admin control panel for system-wide operations."""
    import os
    from app.routes.ai import is_ai_enabled
    
    # Get system-wide statistics
    stats = {
        'total_pods': POD.query.count(),
        'total_territories': Territory.query.count(),
        'total_sellers': Seller.query.count(),
        'total_customers': Customer.query.count(),
        'total_topics': Topic.query.count(),
        'total_call_logs': CallLog.query.count(),
        'total_revenue_records': CustomerRevenueData.query.count() + ProductRevenueData.query.count(),
        'total_revenue_analyses': RevenueAnalysis.query.count(),
        'total_revenue_imports': RevenueImport.query.count(),
        'total_milestones': Milestone.query.count(),
        'total_opportunities': Opportunity.query.count(),
        'total_msx_tasks': MsxTask.query.count()
    }
    
    # AI configuration status
    ai_enabled = is_ai_enabled()
    ai_config = {
        'enabled': ai_enabled,
        'endpoint': os.environ.get('AZURE_OPENAI_ENDPOINT', ''),
        'deployment': os.environ.get('AZURE_OPENAI_DEPLOYMENT', ''),
        'has_credentials': bool(
            os.environ.get('AZURE_CLIENT_ID')
            and os.environ.get('AZURE_CLIENT_SECRET')
            and os.environ.get('AZURE_TENANT_ID')
        )
    }
    
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


@admin_bp.route('/api/admin/clear-revenue', methods=['POST'])
def api_clear_revenue_data():
    """Delete all revenue data (imports, records, analyses, engagements, config)."""
    try:
        deleted = {}
        deleted['engagements'] = RevenueEngagement.query.delete()
        deleted['analyses'] = RevenueAnalysis.query.delete()
        deleted['product_records'] = ProductRevenueData.query.delete()
        deleted['bucket_records'] = CustomerRevenueData.query.delete()
        deleted['imports'] = RevenueImport.query.delete()
        deleted['configs'] = RevenueConfig.query.delete()
        # Reset sync statuses so wizard/UI returns to clean state
        SyncStatus.reset('revenue_import')
        SyncStatus.reset('revenue_analysis')
        db.session.commit()
        total = sum(deleted.values())
        return jsonify({
            'success': True,
            'message': f'Deleted {total} revenue records.',
            'details': deleted
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/admin/clear-milestones', methods=['POST'])
def api_clear_milestone_data():
    """Delete all milestone and opportunity data (milestones, opportunities, tasks, associations)."""
    try:
        deleted = {}
        # Clear associations first (FK constraints)
        deleted['call_log_links'] = db.session.execute(
            call_logs_milestones.delete()
        ).rowcount
        deleted['tasks'] = MsxTask.query.delete()
        deleted['milestones'] = Milestone.query.delete()
        deleted['opportunities'] = Opportunity.query.delete()
        # Reset sync status so wizard/UI returns to clean state
        SyncStatus.reset('milestones')
        db.session.commit()
        total = sum(deleted.values())
        return jsonify({
            'success': True,
            'message': f'Deleted {total} milestone/opportunity records.',
            'details': deleted
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# API routes
@admin_bp.route('/api/admin/domain/add', methods=['POST'])
def api_admin_domain_add():
    """Placeholder for domain add (no longer used but route kept for compatibility)."""
    return jsonify({'success': False, 'error': 'This endpoint is no longer available'}), 410


@admin_bp.route('/api/admin/ai-config/test', methods=['POST'])
def api_admin_ai_config_test():
    """Test AI configuration by making a sample API call using Entra ID auth.
    
    All connection details are read from environment variables.
    """
    import os
    from app.routes.ai import get_azure_openai_client, get_openai_deployment
    
    endpoint_url = os.environ.get('AZURE_OPENAI_ENDPOINT', '')
    deployment_name = get_openai_deployment()
    
    # Validate required fields
    if not endpoint_url or not deployment_name:
        return jsonify({'error': 'Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_DEPLOYMENT in .env file'}), 400
    
    # Check for service principal credentials in environment
    client_id = os.environ.get('AZURE_CLIENT_ID')
    client_secret = os.environ.get('AZURE_CLIENT_SECRET')
    tenant_id = os.environ.get('AZURE_TENANT_ID')
    
    if not all([client_id, client_secret, tenant_id]):
        return jsonify({'error': 'Missing Azure service principal environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)'}), 400
    
    try:
        client = get_azure_openai_client()
        
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


@admin_bp.route('/api/admin/update-check', methods=['GET'])
def api_update_check():
    """Check for available updates and return current state."""
    from app.services.update_checker import get_update_state, check_for_updates
    
    # If force refresh requested, run the check now
    if request.args.get('refresh') == '1':
        state = check_for_updates()
    else:
        state = get_update_state()
    
    # Include dismissed commit from user prefs
    pref = UserPreference.query.first()
    dismissed = pref.dismissed_update_commit if pref else None
    
    # Update is "new" (show badge) if available and not dismissed for this remote commit
    state['dismissed'] = dismissed == state.get('remote_commit')
    state['show_badge'] = state.get('available', False) and not state['dismissed']
    
    return jsonify(state)


@admin_bp.route('/api/admin/update-dismiss', methods=['POST'])
def api_update_dismiss():
    """Dismiss the current update notification."""
    from app.services.update_checker import get_update_state
    
    state = get_update_state()
    remote_commit = state.get('remote_commit')
    
    if not remote_commit:
        return jsonify({'error': 'No update to dismiss'}), 400
    
    pref = UserPreference.query.first()
    if pref:
        pref.dismissed_update_commit = remote_commit
        db.session.commit()
    
    return jsonify({'dismissed': True, 'commit': remote_commit})


@admin_bp.route('/api/admin/deploy', methods=['POST'])
def api_deploy():
    """Launch start.ps1 -Force as a detached process. The server will restart."""
    import os
    import subprocess
    
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    start_script = os.path.join(repo_root, 'start.ps1')
    data_dir = os.path.join(repo_root, 'data')
    log_file = os.path.join(data_dir, 'deploy.log')
    
    if not os.path.exists(start_script):
        return jsonify({'error': 'start.ps1 not found'}), 404
    
    # Ensure data directory exists for the log file
    os.makedirs(data_dir, exist_ok=True)
    
    try:
        # Launch start.ps1 -Force as a detached process with output logged.
        # The server is already running elevated (started via deploy.bat),
        # so the child inherits elevation -- no -Verb RunAs needed.
        # Use PowerShell -Command with *> to capture ALL output streams to a log file.
        subprocess.Popen(
            [
                'powershell', '-ExecutionPolicy', 'Bypass', '-Command',
                f'& "{start_script}" -Force *> "{log_file}"'
            ],
            cwd=repo_root,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True
        )
        return jsonify({'deploying': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/admin/deploy-log')
def api_deploy_log():
    """Read the deploy log file for debugging."""
    import os
    
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_file = os.path.join(repo_root, 'data', 'deploy.log')
    
    if not os.path.exists(log_file):
        return jsonify({'log': 'No deploy log found.', 'exists': False})
    
    try:
        mtime = os.path.getmtime(log_file)
        from datetime import datetime
        modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({'log': content, 'exists': True, 'modified': modified})
    except Exception as e:
        return jsonify({'log': f'Error reading log: {e}', 'exists': False})

