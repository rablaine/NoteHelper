"""
MSX Integration Routes.

Provides API endpoints for MSX (Dynamics 365) integration:
- Authentication status
- Token refresh
- TPID account lookup
- Connection testing
"""

from flask import Blueprint, jsonify, request
import logging

from app.services.msx_auth import (
    get_msx_auth_status,
    refresh_token,
    clear_token_cache,
    start_token_refresh_job,
)
from app.services.msx_api import test_connection, lookup_account_by_tpid

logger = logging.getLogger(__name__)

msx_bp = Blueprint('msx', __name__, url_prefix='/api/msx')


@msx_bp.route('/status')
def auth_status():
    """Get current MSX authentication status."""
    status = get_msx_auth_status()
    
    # Convert datetime to ISO string for JSON
    if status.get("expires_on"):
        status["expires_on"] = status["expires_on"].isoformat()
    if status.get("last_refresh"):
        status["last_refresh"] = status["last_refresh"].isoformat()
    
    return jsonify(status)


@msx_bp.route('/refresh', methods=['POST'])
def refresh():
    """Manually refresh the MSX token."""
    success = refresh_token()
    status = get_msx_auth_status()
    
    # Convert datetime to ISO string for JSON
    if status.get("expires_on"):
        status["expires_on"] = status["expires_on"].isoformat()
    if status.get("last_refresh"):
        status["last_refresh"] = status["last_refresh"].isoformat()
    
    return jsonify({
        "success": success,
        "status": status
    })


@msx_bp.route('/clear', methods=['POST'])
def clear():
    """Clear cached MSX tokens."""
    clear_token_cache()
    return jsonify({"success": True, "message": "Token cache cleared"})


@msx_bp.route('/test')
def test():
    """Test MSX connection by calling WhoAmI."""
    result = test_connection()
    return jsonify(result)


@msx_bp.route('/lookup-tpid/<tpid>')
def lookup_tpid(tpid: str):
    """
    Look up an MSX account by TPID.
    
    Returns:
        JSON with accounts found and direct MSX URL if exactly one match.
    """
    result = lookup_account_by_tpid(tpid)
    return jsonify(result)


@msx_bp.route('/start-refresh-job', methods=['POST'])
def start_refresh():
    """Start the background token refresh job."""
    interval = request.json.get('interval', 300) if request.is_json else 300
    start_token_refresh_job(interval_seconds=interval)
    return jsonify({"success": True, "message": f"Refresh job started (interval: {interval}s)"})
