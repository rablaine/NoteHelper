"""
MSX Integration Routes.

Provides API endpoints for MSX (Dynamics 365) integration:
- Authentication status and device code flow
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
    start_device_code_flow,
    get_device_code_status,
    cancel_device_code_flow,
)
from app.services.msx_api import (
    test_connection,
    lookup_account_by_tpid,
    get_milestones_by_account,
    extract_account_id_from_url,
    create_task,
    TASK_CATEGORIES,
    query_entity,
    get_current_user,
    get_entity_metadata,
    explore_user_territories,
    get_my_accounts,
    get_accounts_for_territories,
)
from app.models import Customer, Milestone, db

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
    
    Args (query params):
        customer_name: Optional customer name for better matching.
    
    Returns:
        JSON with accounts found and direct MSX URL if exactly one match.
    """
    customer_name = request.args.get('customer_name')
    result = lookup_account_by_tpid(tpid, customer_name=customer_name)
    return jsonify(result)


@msx_bp.route('/start-refresh-job', methods=['POST'])
def start_refresh():
    """Start the background token refresh job."""
    interval = request.json.get('interval', 300) if request.is_json else 300
    start_token_refresh_job(interval_seconds=interval)
    return jsonify({"success": True, "message": f"Refresh job started (interval: {interval}s)"})


@msx_bp.route('/device-code/start', methods=['POST'])
def device_code_start():
    """
    Start the device code authentication flow.
    
    Returns the device code and URL for the user to complete login.
    """
    result = start_device_code_flow()
    return jsonify(result)


@msx_bp.route('/device-code/status')
def device_code_status():
    """
    Check the status of an active device code flow.
    
    Poll this endpoint to know when the user has completed login.
    """
    status = get_device_code_status()
    
    # If completed successfully, also return the updated auth status
    if status.get("completed") and status.get("success"):
        auth_status = get_msx_auth_status()
        if auth_status.get("expires_on"):
            auth_status["expires_on"] = auth_status["expires_on"].isoformat()
        if auth_status.get("last_refresh"):
            auth_status["last_refresh"] = auth_status["last_refresh"].isoformat()
        status["auth_status"] = auth_status
    
    return jsonify(status)


@msx_bp.route('/device-code/cancel', methods=['POST'])
def device_code_cancel():
    """Cancel any active device code flow."""
    cancel_device_code_flow()
    return jsonify({"success": True, "message": "Device code flow cancelled"})


# -----------------------------------------------------------------------------
# Milestone Routes
# -----------------------------------------------------------------------------

@msx_bp.route('/milestones/<account_id>')
def get_milestones(account_id: str):
    """
    Get all milestones for an account.
    
    Returns milestones sorted by status (Active first, then Blocked, Completed, etc.)
    with indication of whether each milestone is used in any call logs.
    """
    result = get_milestones_by_account(account_id)
    
    if not result.get("success"):
        return jsonify(result)
    
    # Check which milestones are already used in call logs
    milestones = result.get("milestones", [])
    for milestone_data in milestones:
        msx_milestone_id = milestone_data.get("id")
        if msx_milestone_id:
            # Check if any milestone in our DB has this MSX ID
            existing = Milestone.query.filter_by(msx_milestone_id=msx_milestone_id).first()
            if existing and existing.call_logs:
                milestone_data["used_in_call_logs"] = len(existing.call_logs)
                milestone_data["local_milestone_id"] = existing.id
            else:
                milestone_data["used_in_call_logs"] = 0
                milestone_data["local_milestone_id"] = existing.id if existing else None
    
    return jsonify(result)


@msx_bp.route('/milestones-for-customer/<int:customer_id>')
def get_milestones_for_customer(customer_id: int):
    """
    Get all milestones for a customer using their TPID URL.
    
    Extracts the account ID from the customer's tpid_url and fetches milestones.
    """
    customer = Customer.query.get(customer_id)
    if not customer:
        return jsonify({"success": False, "error": "Customer not found"})
    
    if not customer.tpid_url:
        return jsonify({
            "success": False, 
            "error": "Customer has no MSX account linked",
            "needs_tpid": True
        })
    
    # Extract account ID from the tpid_url
    account_id = extract_account_id_from_url(customer.tpid_url)
    if not account_id:
        return jsonify({
            "success": False,
            "error": "Could not extract account ID from customer's MSX URL"
        })
    
    # Get milestones
    result = get_milestones_by_account(account_id)
    
    if not result.get("success"):
        return jsonify(result)
    
    # Check which milestones are already used in call logs
    milestones = result.get("milestones", [])
    for milestone_data in milestones:
        msx_milestone_id = milestone_data.get("id")
        if msx_milestone_id:
            existing = Milestone.query.filter_by(msx_milestone_id=msx_milestone_id).first()
            if existing and existing.call_logs:
                milestone_data["used_in_call_logs"] = len(existing.call_logs)
                milestone_data["local_milestone_id"] = existing.id
            else:
                milestone_data["used_in_call_logs"] = 0
                milestone_data["local_milestone_id"] = existing.id if existing else None
    
    return jsonify(result)


# -----------------------------------------------------------------------------
# Task Routes
# -----------------------------------------------------------------------------

@msx_bp.route('/task-categories')
def get_task_categories():
    """
    Get all available task categories.
    
    Returns categories with HOK flags for UI highlighting.
    """
    return jsonify({
        "success": True,
        "categories": TASK_CATEGORIES
    })


@msx_bp.route('/tasks', methods=['POST'])
def create_msx_task():
    """
    Create a task on a milestone in MSX.
    
    Expected JSON body:
        milestone_id: MSX milestone GUID
        subject: Task title
        task_category: Category code (e.g., 861980004)
        duration_minutes: Duration in minutes (default: 60)
        description: Optional task description
    
    Returns:
        task_id: MSX task GUID
        task_url: Direct URL to the task in MSX
    """
    if not request.is_json:
        return jsonify({"success": False, "error": "JSON body required"}), 400
    
    data = request.json
    milestone_id = data.get("milestone_id")
    subject = data.get("subject")
    task_category = data.get("task_category")
    duration_minutes = data.get("duration_minutes", 60)
    description = data.get("description")
    
    if not milestone_id:
        return jsonify({"success": False, "error": "milestone_id required"}), 400
    if not subject:
        return jsonify({"success": False, "error": "subject required"}), 400
    if not task_category:
        return jsonify({"success": False, "error": "task_category required"}), 400
    
    result = create_task(
        milestone_id=milestone_id,
        subject=subject,
        task_category=task_category,
        duration_minutes=duration_minutes,
        description=description
    )
    
    return jsonify(result)


# -----------------------------------------------------------------------------
# Exploration / Schema Discovery Routes
# -----------------------------------------------------------------------------

@msx_bp.route('/explore/me')
def explore_me():
    """
    Get the current authenticated user's details.
    
    Returns user ID, name, email, title, and other profile info.
    """
    result = get_current_user()
    return jsonify(result)


@msx_bp.route('/explore/my-accounts')
def explore_my_accounts():
    """
    Get all accounts the current user has access to via team memberships.
    
    Uses the pattern: user → teammemberships → teams → accounts
    
    Returns list of accounts with name, TPID, owner, and ATU info.
    """
    result = get_my_accounts()
    return jsonify(result)


@msx_bp.route('/explore/accounts-by-territory', methods=['POST'])
def explore_accounts_by_territory():
    """
    Get all accounts for specified territories.
    
    POST JSON body:
        territories: List of territory names (e.g., ["East.SMECC.SDP.0603"])
    
    Returns accounts with name, TPID, seller, and territory info.
    
    This is the recommended approach for seeding the database - provide
    your known territory names and get all accounts for those territories.
    """
    if not request.is_json:
        return jsonify({"success": False, "error": "JSON body required"}), 400
    
    territories = request.json.get("territories", [])
    if not territories:
        return jsonify({"success": False, "error": "territories list required"}), 400
    
    result = get_accounts_for_territories(territories)
    return jsonify(result)


@msx_bp.route('/explore/territories')
def explore_territories():
    """
    Explore what territories and accounts the current user has access to.
    
    Tries multiple discovery approaches to find assignments.
    """
    result = explore_user_territories()
    return jsonify(result)


@msx_bp.route('/explore/entity/<entity_name>')
def explore_entity(entity_name: str):
    """
    Query any MSX entity for data discovery.
    
    Query params:
        select: Comma-separated field names (optional)
        filter: OData $filter expression (optional)
        expand: OData $expand expression (optional)
        top: Max records (default 10, max 100)
        orderby: OData $orderby expression (optional)
    
    Examples:
        /api/msx/explore/entity/accounts?top=5&select=name,msp_mstopparentid
        /api/msx/explore/entity/systemusers?filter=contains(fullname,'Alex')
        /api/msx/explore/entity/territories?top=20
    """
    select = request.args.get('select')
    filter_query = request.args.get('filter')
    expand = request.args.get('expand')
    order_by = request.args.get('orderby')
    
    try:
        top = min(int(request.args.get('top', 10)), 100)
    except ValueError:
        top = 10
    
    select_list = select.split(',') if select else None
    
    result = query_entity(
        entity_name=entity_name,
        select=select_list,
        filter_query=filter_query,
        expand=expand,
        top=top,
        order_by=order_by
    )
    return jsonify(result)


@msx_bp.route('/explore/metadata/<entity_name>')
def explore_metadata(entity_name: str):
    """
    Get the schema/metadata for an entity to discover available fields.
    
    Examples:
        /api/msx/explore/metadata/account
        /api/msx/explore/metadata/systemuser
        /api/msx/explore/metadata/territory
        /api/msx/explore/metadata/msp_milestone
    
    Note: Use singular logical name (account, not accounts).
    """
    result = get_entity_metadata(entity_name)
    return jsonify(result)
