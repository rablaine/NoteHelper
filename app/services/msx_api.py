"""
MSX (Dynamics 365) API Client.

This module provides functions to call the MSX CRM API for:
- Account lookup by TPID
- Connection testing (WhoAmI)

Uses msx_auth for token management.
"""

import requests
import logging
from typing import Optional, Dict, Any, List

from app.services.msx_auth import get_msx_token, refresh_token, CRM_BASE_URL

logger = logging.getLogger(__name__)

# MSX app ID for account URLs
MSX_APP_ID = "fe0c3504-3700-e911-a849-000d3a10b7cc"

# Request timeout
REQUEST_TIMEOUT = 20

# Standard headers for OData requests
def _get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Prefer": "odata.include-annotations=\"*\"",
    }


def _msx_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict] = None,
    retry_on_auth_failure: bool = True
) -> requests.Response:
    """
    Make an MSX API request with automatic token refresh on 401/403.
    
    If we get a 401 (expired) or 403 (access denied), forces a token refresh
    and retries once. This handles cases where the cached token looks valid
    but has been invalidated server-side.
    
    Args:
        method: HTTP method ('GET', 'POST', etc.)
        url: Full URL to request
        headers: Request headers (if None, will get fresh token and build headers)
        json_data: JSON body for POST requests
        retry_on_auth_failure: Whether to auto-retry on 401/403 (default True)
        
    Returns:
        requests.Response object
        
    Raises:
        requests.exceptions.Timeout, ConnectionError, etc.
    """
    # Get token and build headers if not provided
    if headers is None:
        token = get_msx_token()
        if not token:
            # Create a fake response for "not authenticated"
            response = requests.models.Response()
            response.status_code = 401
            response._content = b'{"error": "Not authenticated"}'
            return response
        headers = _get_headers(token)
    
    # Make the request
    if method.upper() == 'GET':
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    elif method.upper() == 'POST':
        response = requests.post(url, headers=headers, json=json_data, timeout=REQUEST_TIMEOUT)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")
    
    # Check for auth failures that might be due to stale token
    if response.status_code in (401, 403) and retry_on_auth_failure:
        logger.info(f"Got {response.status_code} from MSX, forcing token refresh and retrying...")
        
        # Force token refresh
        refresh_success = refresh_token()
        if not refresh_success:
            logger.warning("Token refresh failed, returning original error response")
            return response
        
        # Get fresh token and rebuild headers
        fresh_token = get_msx_token()
        if not fresh_token:
            logger.warning("No token after refresh, returning original error response")
            return response
        
        fresh_headers = _get_headers(fresh_token)
        
        # Retry the request (without retry flag to prevent infinite loop)
        logger.info("Retrying MSX request with fresh token...")
        if method.upper() == 'GET':
            response = requests.get(url, headers=fresh_headers, timeout=REQUEST_TIMEOUT)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=fresh_headers, json=json_data, timeout=REQUEST_TIMEOUT)
        
        if response.status_code in (401, 403):
            logger.warning(f"Still got {response.status_code} after token refresh - likely a real permission issue")
    
    return response


def test_connection() -> Dict[str, Any]:
    """
    Test the MSX connection by calling WhoAmI.
    
    Returns:
        Dict with:
        - success: bool
        - user_id: str (GUID) if successful
        - error: str if failed
    """
    try:
        response = _msx_request('GET', f"{CRM_BASE_URL}/WhoAmI")
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "user_id": data.get("UserId"),
                "business_unit_id": data.get("BusinessUnitId"),
                "organization_id": data.get("OrganizationId"),
            }
        elif response.status_code == 401:
            return {"success": False, "error": "Not authenticated. Run 'az login' first."}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out. Check VPN connection."}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error (VPN?): {str(e)[:100]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    if not name:
        return ""
    # Lowercase, remove common suffixes, extra whitespace
    normalized = name.lower().strip()
    for suffix in [" inc", " inc.", " llc", " llc.", " corp", " corp.", " co", " co.", " ltd", " ltd."]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
    return normalized


def _names_similar(name1: str, name2: str) -> bool:
    """
    Check if two company names are similar enough to be confident they match.
    Returns True if names are similar, False if they're too different.
    """
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)
    
    if not n1 or not n2:
        return False
    
    # Exact match after normalization
    if n1 == n2:
        return True
    
    # One contains the other (handles "ABC" vs "ABC Company")
    if n1 in n2 or n2 in n1:
        return True
    
    # Check if first word matches (handles "Acme Corp" vs "Acme Industries")
    words1 = n1.split()
    words2 = n2.split()
    if words1 and words2 and words1[0] == words2[0] and len(words1[0]) >= 4:
        return True
    
    return False


def lookup_account_by_tpid(tpid: str, customer_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Look up an MSX account by TPID (msp_mstopparentid).
    
    Args:
        tpid: The Top Parent ID to search for.
        customer_name: Optional customer name to match against (for better auto-selection).
        
    Returns:
        Dict with:
        - success: bool
        - accounts: List of matching accounts (each with accountid, name, msp_mstopparentid)
        - url: Direct MSX URL if exactly one match
        - error: str if failed
    """
    # Sanitize TPID - should be numeric
    tpid_clean = str(tpid).strip()
    
    try:
        # Build OData query - include parenting level to identify "Top" parent
        url = (
            f"{CRM_BASE_URL}/accounts"
            f"?$filter=msp_mstopparentid eq '{tpid_clean}'"
            f"&$select=accountid,name,msp_mstopparentid,msp_parentinglevelcode"
        )
        
        response = _msx_request('GET', url)
        
        if response.status_code == 200:
            data = response.json()
            raw_accounts = data.get("value", [])
            
            # Process accounts - extract parenting level from OData annotations
            accounts = []
            top_accounts = []  # Track ALL top-level accounts
            name_match = None  # Account matching customer name
            normalized_customer = _normalize_name(customer_name) if customer_name else None
            
            for raw in raw_accounts:
                account = {
                    "accountid": raw.get("accountid"),
                    "name": raw.get("name"),
                    "msp_mstopparentid": raw.get("msp_mstopparentid"),
                    "parenting_level": raw.get(
                        "msp_parentinglevelcode@OData.Community.Display.V1.FormattedValue",
                        raw.get("msp_parentinglevelcode", "Unknown")
                    ),
                    "url": build_account_url(raw.get("accountid")),
                }
                accounts.append(account)
                
                # Track all "Top" parent accounts
                if account["parenting_level"] and "top" in str(account["parenting_level"]).lower():
                    top_accounts.append(account)
                
                # Check for name match (if customer_name provided)
                if normalized_customer and not name_match:
                    normalized_account = _normalize_name(account["name"])
                    if normalized_account == normalized_customer:
                        name_match = account
            
            result = {
                "success": True,
                "accounts": accounts,
                "count": len(accounts),
            }
            
            # Selection priority:
            # 1. If customer name matches an account, use that (most confident)
            # 2. If only one account AND names are similar, use it
            # 3. If exactly ONE Top parent AND names similar, use it
            # 4. Otherwise, don't auto-select (let user choose)
            
            if name_match:
                # Found matching customer name - most confident
                result["url"] = name_match["url"]
                result["account_name"] = name_match["name"]
                result["name_match"] = True
            elif len(accounts) == 1:
                # Single account - check if name is similar before auto-selecting
                if customer_name and _names_similar(customer_name, accounts[0]["name"]):
                    result["url"] = accounts[0]["url"]
                    result["account_name"] = accounts[0]["name"]
                elif not customer_name:
                    # No customer name provided - can't verify, still auto-select
                    result["url"] = accounts[0]["url"]
                    result["account_name"] = accounts[0]["name"]
                else:
                    # Name mismatch warning - don't auto-select
                    result["name_mismatch"] = True
                    result["msx_account_name"] = accounts[0]["name"]
            elif len(top_accounts) == 1:
                # Single Top parent - check name similarity
                if customer_name and _names_similar(customer_name, top_accounts[0]["name"]):
                    result["url"] = top_accounts[0]["url"]
                    result["account_name"] = top_accounts[0]["name"]
                    result["top_parent"] = True
                elif not customer_name:
                    result["url"] = top_accounts[0]["url"]
                    result["account_name"] = top_accounts[0]["name"]
                    result["top_parent"] = True
                else:
                    # Name mismatch warning
                    result["name_mismatch"] = True
                    result["msx_account_name"] = top_accounts[0]["name"]
                    result["multiple_tops"] = 0  # Flag to show options
            elif len(top_accounts) > 1:
                # Exactly one Top parent - safe to auto-select
                result["url"] = top_accounts[0]["url"]
                result["account_name"] = top_accounts[0]["name"]
                result["top_parent"] = True
            elif len(top_accounts) > 1:
                # Multiple Top parents - show them for selection
                result["multiple_tops"] = len(top_accounts)
            
            return result
            
        elif response.status_code == 401:
            return {"success": False, "error": "Not authenticated. Run 'az login' first."}
        elif response.status_code == 403:
            return {"success": False, "error": "Access denied. You may not have permission to query accounts."}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out. Check VPN connection."}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error (VPN?): {str(e)[:100]}"}
    except Exception as e:
        logger.exception(f"Error looking up TPID {tpid}")
        return {"success": False, "error": str(e)}


def build_account_url(account_id: str) -> str:
    """
    Build a direct MSX URL for an account.
    
    Args:
        account_id: The account GUID.
        
    Returns:
        Full MSX URL to open the account record.
    """
    return (
        f"https://microsoftsales.crm.dynamics.com/main.aspx"
        f"?appid={MSX_APP_ID}"
        f"&pagetype=entityrecord"
        f"&etn=account"
        f"&id={account_id}"
    )


def build_milestone_url(milestone_id: str) -> str:
    """
    Build a direct MSX URL for a milestone.
    
    Args:
        milestone_id: The milestone GUID (msp_engagementmilestoneid).
        
    Returns:
        Full MSX URL to open the milestone record.
    """
    return (
        f"https://microsoftsales.crm.dynamics.com/main.aspx"
        f"?appid={MSX_APP_ID}"
        f"&pagetype=entityrecord"
        f"&etn=msp_engagementmilestone"
        f"&id={milestone_id}"
    )


def build_task_url(task_id: str) -> str:
    """
    Build a direct MSX URL for a task.
    
    Args:
        task_id: The task GUID (activityid).
        
    Returns:
        Full MSX URL to open the task record.
    """
    return (
        f"https://microsoftsales.crm.dynamics.com/main.aspx"
        f"?appid={MSX_APP_ID}"
        f"&pagetype=entityrecord"
        f"&etn=task"
        f"&id={task_id}"
    )


# Milestone status sort order (lower = more important in UI)
MILESTONE_STATUS_ORDER = {
    'On Track': 1,
    'At Risk': 2,
    'Blocked': 3,
    'Completed': 4,
    'Cancelled': 5,
    'Lost to Competitor': 6,
    'Hygiene/Duplicate': 7,
}

# HOK task categories (eligible for hands-on-keyboard credit)
HOK_TASK_CATEGORIES = {
    861980004,  # Architecture Design Session
    861980006,  # Blocker Escalation
    861980008,  # Briefing
    861980007,  # Consumption Plan
    861980002,  # Demo
    861980005,  # PoC/Pilot
    606820005,  # Technical Close/Win Plan
    861980001,  # Workshop
}

# All task categories
TASK_CATEGORIES = [
    # HOK categories (sorted first)
    {"label": "Architecture Design Session", "value": 861980004, "is_hok": True},
    {"label": "Blocker Escalation", "value": 861980006, "is_hok": True},
    {"label": "Briefing", "value": 861980008, "is_hok": True},
    {"label": "Consumption Plan", "value": 861980007, "is_hok": True},
    {"label": "Demo", "value": 861980002, "is_hok": True},
    {"label": "PoC/Pilot", "value": 861980005, "is_hok": True},
    {"label": "Technical Close/Win Plan", "value": 606820005, "is_hok": True},
    {"label": "Workshop", "value": 861980001, "is_hok": True},
    # Non-HOK categories
    {"label": "ACE", "value": 606820000, "is_hok": False},
    {"label": "Call Back Requested", "value": 861980010, "is_hok": False},
    {"label": "Cross Segment", "value": 606820001, "is_hok": False},
    {"label": "Cross Workload", "value": 606820002, "is_hok": False},
    {"label": "Customer Engagement", "value": 861980000, "is_hok": False},
    {"label": "External (Co-creation of Value)", "value": 861980013, "is_hok": False},
    {"label": "Internal", "value": 861980012, "is_hok": False},
    {"label": "Negotiate Pricing", "value": 861980003, "is_hok": False},
    {"label": "New Partner Request", "value": 861980011, "is_hok": False},
    {"label": "Post Sales", "value": 606820003, "is_hok": False},
    {"label": "RFP/RFI", "value": 861980009, "is_hok": False},
    {"label": "Tech Support", "value": 606820004, "is_hok": False},
]


def extract_account_id_from_url(tpid_url: str) -> Optional[str]:
    """
    Extract the account GUID from an MSX account URL.
    
    Args:
        tpid_url: MSX URL like https://microsoftsales.crm.dynamics.com/main.aspx?...&id={guid}
        
    Returns:
        The account GUID if found, None otherwise.
    """
    if not tpid_url:
        return None
    
    import re
    # Look for id= parameter (GUID format)
    match = re.search(r'[&?]id=([a-f0-9-]{36})', tpid_url, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Also try %7B and %7D encoded braces
    match = re.search(r'[&?]id=%7B([a-f0-9-]{36})%7D', tpid_url, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None


def get_milestones_by_account(account_id: str) -> Dict[str, Any]:
    """
    Get all milestones for an account.
    
    Args:
        account_id: The account GUID.
        
    Returns:
        Dict with:
        - success: bool
        - milestones: List of milestone dicts with id, name, status, number, url, opportunity
        - error: str if failed
    """
    try:
        # Query milestones by parent account
        url = (
            f"{CRM_BASE_URL}/msp_engagementmilestones"
            f"?$filter=_msp_parentaccount_value eq '{account_id}'"
            f"&$select=msp_engagementmilestoneid,msp_name,msp_milestonestatus,"
            f"msp_milestonenumber,_msp_opportunityid_value,msp_monthlyuse,_msp_workloadlkid_value"
            f"&$orderby=msp_name"
        )
        
        response = _msx_request('GET', url)
        
        if response.status_code == 200:
            data = response.json()
            raw_milestones = data.get("value", [])
            
            milestones = []
            for raw in raw_milestones:
                milestone_id = raw.get("msp_engagementmilestoneid")
                status = raw.get(
                    "msp_milestonestatus@OData.Community.Display.V1.FormattedValue",
                    "Unknown"
                )
                status_code = raw.get("msp_milestonestatus")
                opp_name = raw.get(
                    "_msp_opportunityid_value@OData.Community.Display.V1.FormattedValue",
                    ""
                )
                workload = raw.get(
                    "_msp_workloadlkid_value@OData.Community.Display.V1.FormattedValue",
                    ""
                )
                monthly_usage = raw.get("msp_monthlyuse")
                
                milestones.append({
                    "id": milestone_id,
                    "name": raw.get("msp_name", ""),
                    "number": raw.get("msp_milestonenumber", ""),
                    "status": status,
                    "status_code": status_code,
                    "status_sort": MILESTONE_STATUS_ORDER.get(status, 99),
                    "opportunity_name": opp_name,
                    "workload": workload,
                    "monthly_usage": monthly_usage,
                    "url": build_milestone_url(milestone_id),
                })
            
            # Sort by status (active first), then by name
            milestones.sort(key=lambda m: (m["status_sort"], m["name"].lower()))
            
            return {
                "success": True,
                "milestones": milestones,
                "count": len(milestones),
            }
            
        elif response.status_code == 401:
            return {"success": False, "error": "Not authenticated. Run 'az login' first."}
        elif response.status_code == 403:
            return {"success": False, "error": "Access denied. You may not have permission to query milestones."}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out. Check VPN connection."}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error (VPN?): {str(e)[:100]}"}
    except Exception as e:
        logger.exception(f"Error getting milestones for account {account_id}")
        return {"success": False, "error": str(e)}


def get_current_user_id() -> Optional[str]:
    """
    Get the current user's system user ID from MSX.
    
    Returns:
        User GUID if successful, None otherwise.
    """
    result = test_connection()
    if result.get("success"):
        return result.get("user_id")
    return None


def create_task(
    milestone_id: str,
    subject: str,
    task_category: int,
    duration_minutes: int = 60,
    description: str = None,
) -> Dict[str, Any]:
    """
    Create a task in MSX linked to a milestone.
    
    Args:
        milestone_id: The milestone GUID to link the task to.
        subject: Task subject/title.
        task_category: Numeric task category code.
        duration_minutes: Task duration (default 60).
        description: Optional task description.
        
    Returns:
        Dict with:
        - success: bool
        - task_id: str (GUID) if successful
        - task_url: str (MSX URL) if successful
        - error: str if failed
    """
    # Get current user ID for task owner
    user_id = get_current_user_id()
    if not user_id:
        return {"success": False, "error": "Could not determine current user."}
    
    try:
        # Build task payload
        task_data = {
            "subject": subject,
            "msp_taskcategory": task_category,
            "scheduleddurationminutes": duration_minutes,
            "prioritycode": 1,  # Normal priority (0=Low, 1=Normal, 2=High)
            "regardingobjectid_msp_engagementmilestone@odata.bind": f"/msp_engagementmilestones({milestone_id})",
            "ownerid@odata.bind": f"/systemusers({user_id})",
        }
        
        if description:
            task_data["description"] = description
        
        response = _msx_request('POST', f"{CRM_BASE_URL}/tasks", json_data=task_data)
        
        if response.status_code in (200, 201, 204):
            # Extract task ID from OData-EntityId header
            entity_id_header = response.headers.get("OData-EntityId", "")
            task_id = None
            
            import re
            match = re.search(r'tasks\(([a-f0-9-]{36})\)', entity_id_header, re.IGNORECASE)
            if match:
                task_id = match.group(1)
            
            if task_id:
                return {
                    "success": True,
                    "task_id": task_id,
                    "task_url": build_task_url(task_id),
                }
            else:
                return {
                    "success": True,
                    "task_id": None,
                    "task_url": None,
                    "warning": "Task created but could not extract ID from response.",
                }
                
        elif response.status_code == 401:
            return {"success": False, "error": "Not authenticated. Run 'az login' first."}
        elif response.status_code == 403:
            return {"success": False, "error": "Access denied. You may not have permission to create tasks."}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:300]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out. Check VPN connection."}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error (VPN?): {str(e)[:100]}"}
    except Exception as e:
        logger.exception(f"Error creating task for milestone {milestone_id}")
        return {"success": False, "error": str(e)}


# =============================================================================
# MSX Exploration / Schema Discovery Functions
# =============================================================================

def query_entity(
    entity_name: str,
    select: Optional[List[str]] = None,
    filter_query: Optional[str] = None,
    expand: Optional[str] = None,
    top: int = 10,
    order_by: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generic OData query for any MSX entity.
    
    Args:
        entity_name: The entity set name (e.g., 'accounts', 'systemusers', 'territories')
        select: List of fields to return (None = all fields)
        filter_query: OData $filter expression
        expand: OData $expand for related entities
        top: Max records to return (default 10)
        order_by: OData $orderby expression
        
    Returns:
        Dict with success/error and records array
    """
    try:
        # Build query params
        params = [f"$top={top}"]
        
        if select:
            params.append(f"$select={','.join(select)}")
        if filter_query:
            params.append(f"$filter={filter_query}")
        if expand:
            params.append(f"$expand={expand}")
        if order_by:
            params.append(f"$orderby={order_by}")
        
        query_string = "&".join(params)
        url = f"{CRM_BASE_URL}/{entity_name}?{query_string}"
        
        logger.info(f"Querying MSX: {url}")
        response = _msx_request('GET', url)
        
        if response.status_code == 200:
            data = response.json()
            records = data.get("value", [])
            return {
                "success": True,
                "entity": entity_name,
                "count": len(records),
                "records": records,
                "query_url": url
            }
        elif response.status_code == 401:
            return {"success": False, "error": "Not authenticated. Run 'az login' first."}
        elif response.status_code == 404:
            return {"success": False, "error": f"Entity '{entity_name}' not found."}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:500]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out."}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error: {str(e)[:100]}"}
    except Exception as e:
        logger.exception(f"Error querying {entity_name}")
        return {"success": False, "error": str(e)}


def get_current_user() -> Dict[str, Any]:
    """
    Get the current authenticated user's details from MSX.
    
    Returns user ID, name, email, and other useful info.
    """
    try:
        # First get user ID via WhoAmI
        whoami_response = _msx_request('GET', f"{CRM_BASE_URL}/WhoAmI")
        
        if whoami_response.status_code != 200:
            if whoami_response.status_code == 401:
                return {"success": False, "error": "Not authenticated. Run 'az login' first."}
            return {"success": False, "error": f"WhoAmI failed: {whoami_response.status_code}"}
        
        whoami_data = whoami_response.json()
        user_id = whoami_data.get("UserId")
        
        if not user_id:
            return {"success": False, "error": "Could not get user ID from WhoAmI"}
        
        # Now get full user record
        url = f"{CRM_BASE_URL}/systemusers({user_id})"
        response = _msx_request('GET', url)
        
        if response.status_code == 200:
            user_data = response.json()
            return {
                "success": True,
                "user_id": user_id,
                "user": user_data
            }
        else:
            return {
                "success": False,
                "error": f"Failed to get user details: {response.status_code}"
            }
            
    except Exception as e:
        logger.exception("Error getting current user")
        return {"success": False, "error": str(e)}


def get_entity_metadata(entity_name: str) -> Dict[str, Any]:
    """
    Get metadata/schema for an entity to discover available fields.
    
    Args:
        entity_name: Logical name of entity (e.g., 'account', 'systemuser')
        
    Returns:
        Dict with entity attributes and their types
    """
    try:
        # Query the metadata endpoint
        url = f"{CRM_BASE_URL}/EntityDefinitions(LogicalName='{entity_name}')/Attributes"
        response = _msx_request('GET', url)
        
        if response.status_code == 200:
            data = response.json()
            attributes = data.get("value", [])
            
            # Simplify the output - just key info
            simplified = []
            for attr in attributes:
                simplified.append({
                    "name": attr.get("LogicalName"),
                    "display_name": attr.get("DisplayName", {}).get("UserLocalizedLabel", {}).get("Label") if isinstance(attr.get("DisplayName"), dict) else None,
                    "type": attr.get("AttributeType"),
                    "description": attr.get("Description", {}).get("UserLocalizedLabel", {}).get("Label") if isinstance(attr.get("Description"), dict) else None,
                })
            
            # Sort by name
            simplified.sort(key=lambda x: x.get("name", ""))
            
            return {
                "success": True,
                "entity": entity_name,
                "attribute_count": len(simplified),
                "attributes": simplified
            }
        elif response.status_code == 404:
            return {"success": False, "error": f"Entity '{entity_name}' not found"}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:300]}"
            }
            
    except Exception as e:
        logger.exception(f"Error getting metadata for {entity_name}")
        return {"success": False, "error": str(e)}


def explore_user_territories() -> Dict[str, Any]:
    """
    Explore what territories/accounts the current user has access to.
    
    Tries multiple approaches to find the user's assigned territories/customers.
    """
    results = {
        "success": True,
        "explorations": []
    }
    
    # 1. Get current user
    user_result = get_current_user()
    if not user_result.get("success"):
        return user_result
    
    user = user_result.get("user", {})
    user_id = user_result.get("user_id")
    
    results["current_user"] = {
        "id": user_id,
        "name": user.get("fullname"),
        "email": user.get("internalemailaddress"),
        "title": user.get("title"),
        "business_unit": user.get("_businessunitid_value"),
        "territory": user.get("_territoryid_value"),  # Direct territory assignment
    }
    
    # 2. Check if user has a direct territory assignment
    if user.get("_territoryid_value"):
        territory_id = user.get("_territoryid_value")
        territory_result = query_entity(
            "territories",
            filter_query=f"territoryid eq {territory_id}",
            top=1
        )
        if territory_result.get("success") and territory_result.get("records"):
            results["direct_territory"] = territory_result["records"][0]
    
    # 3. Look for team memberships that might link to territories
    team_result = query_entity(
        "teammemberships",
        filter_query=f"systemuserid eq {user_id}",
        top=50
    )
    if team_result.get("success"):
        results["explorations"].append({
            "query": "User team memberships",
            "result": team_result
        })
    
    # 4. Look for accounts where user is owner
    owned_accounts = query_entity(
        "accounts",
        select=["accountid", "name", "msp_mstopparentid", "msp_accountsegment"],
        filter_query=f"_ownerid_value eq {user_id}",
        top=20
    )
    if owned_accounts.get("success"):
        results["owned_accounts"] = owned_accounts.get("records", [])
    
    # 5. Look for msp_accountteammember or similar
    # Try to find account team member records for this user
    try:
        team_member_result = query_entity(
            "msp_accountteammembers",
            filter_query=f"_msp_user_value eq {user_id}",
            top=50
        )
        if team_member_result.get("success"):
            results["explorations"].append({
                "query": "Account team memberships (msp_accountteammembers)",
                "result": team_member_result
            })
    except Exception:
        pass  # Entity might not exist
    
    return results


def get_my_accounts() -> Dict[str, Any]:
    """
    Get all accounts the current user has access to via team memberships.
    
    Pattern:
    1. Get current user ID via WhoAmI
    2. Query teammemberships for my user ID (get team IDs)
    3. Query teams for those IDs to get regardingobjectid (account IDs)
    4. Query accounts to get names, TPIDs, sellers, territories
    
    Returns:
        Dict with accounts array containing name, tpid, territory, seller info
    """
    try:
        # 1. Get current user ID
        user_result = get_current_user()
        if not user_result.get("success"):
            return user_result
        
        user_id = user_result.get("user_id")
        user_name = user_result.get("user", {}).get("fullname", "Unknown")
        
        # 2. Get my team memberships (cap at 200 to be reasonable)
        team_memberships = query_entity(
            "teammemberships",
            filter_query=f"systemuserid eq {user_id}",
            top=200
        )
        
        if not team_memberships.get("success"):
            return team_memberships
        
        team_ids = [tm.get("teamid") for tm in team_memberships.get("records", []) if tm.get("teamid")]
        
        if not team_ids:
            return {
                "success": True,
                "accounts": [],
                "message": "No team memberships found"
            }
        
        # 3. Get teams to find regardingobjectid (account IDs)
        # Query in batches to avoid URL length limits
        account_ids = set()
        batch_size = 15
        
        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i:i+batch_size]
            filter_parts = [f"teamid eq {tid}" for tid in batch]
            filter_query = " or ".join(filter_parts)
            
            teams_result = query_entity(
                "teams",
                select=["teamid", "name", "_regardingobjectid_value"],
                filter_query=filter_query,
                top=50
            )
            
            if teams_result.get("success"):
                for team in teams_result.get("records", []):
                    # Check if this team is associated with an account
                    regard_id = team.get("_regardingobjectid_value")
                    if regard_id:
                        account_ids.add(regard_id)
        
        if not account_ids:
            return {
                "success": True,
                "accounts": [],
                "message": "No accounts found via team memberships"
            }
        
        # 4. Get account details
        accounts = []
        account_list = list(account_ids)
        
        for i in range(0, len(account_list), batch_size):
            batch = account_list[i:i+batch_size]
            filter_parts = [f"accountid eq {aid}" for aid in batch]
            filter_query = " or ".join(filter_parts)
            
            accounts_result = query_entity(
                "accounts",
                select=[
                    "accountid", "name", "msp_mstopparentid",
                    "_ownerid_value", "_msp_atu_value"
                ],
                filter_query=filter_query,
                top=50
            )
            
            if accounts_result.get("success"):
                for acct in accounts_result.get("records", []):
                    accounts.append({
                        "account_id": acct.get("accountid"),
                        "name": acct.get("name"),
                        "tpid": acct.get("msp_mstopparentid"),
                        "owner_id": acct.get("_ownerid_value"),
                        "owner_name": acct.get("_ownerid_value@OData.Community.Display.V1.FormattedValue"),
                        "atu_id": acct.get("_msp_atu_value"),
                        "atu_name": acct.get("_msp_atu_value@OData.Community.Display.V1.FormattedValue"),
                    })
        
        # Sort by name
        accounts.sort(key=lambda x: (x.get("name") or "").lower())
        
        return {
            "success": True,
            "user": user_name,
            "user_id": user_id,
            "team_count": len(team_ids),
            "account_count": len(accounts),
            "accounts": accounts
        }
        
    except Exception as e:
        logger.exception("Error getting my accounts")
        return {"success": False, "error": str(e)}


def get_accounts_for_territories(territory_names: List[str]) -> Dict[str, Any]:
    """
    Get all accounts for a list of territory names.
    
    Args:
        territory_names: List of territory names (e.g., ["East.SMECC.SDP.0603", "East.SMECC.MAA.0601"])
        
    Returns:
        Dict with:
        - success: bool
        - accounts: list of account dicts with name, tpid, seller, territory
        - territories: list of territory info that was found
    """
    try:
        # 1. Look up territory IDs from names
        territories = []
        for name in territory_names:
            result = query_entity(
                "territories",
                select=["territoryid", "name"],
                filter_query=f"name eq '{name}'",
                top=1
            )
            if result.get("success") and result.get("records"):
                territories.append(result["records"][0])
        
        if not territories:
            return {
                "success": False,
                "error": "No territories found matching the provided names"
            }
        
        # 2. Query accounts for each territory
        accounts = []
        for territory in territories:
            territory_id = territory.get("territoryid")
            territory_name = territory.get("name")
            
            # Query accounts with this territory - cap at 200 per territory
            accounts_result = query_entity(
                "accounts",
                select=["accountid", "name", "msp_mstopparentid", "_ownerid_value", "_territoryid_value"],
                filter_query=f"_territoryid_value eq {territory_id}",
                top=200
            )
            
            if accounts_result.get("success"):
                for acct in accounts_result.get("records", []):
                    accounts.append({
                        "account_id": acct.get("accountid"),
                        "name": acct.get("name"),
                        "tpid": acct.get("msp_mstopparentid"),
                        "seller_id": acct.get("_ownerid_value"),
                        "seller_name": acct.get("_ownerid_value@OData.Community.Display.V1.FormattedValue"),
                        "territory_id": territory_id,
                        "territory_name": territory_name,
                    })
        
        # Sort by name
        accounts.sort(key=lambda x: (x.get("name") or "").lower())
        
        return {
            "success": True,
            "territory_count": len(territories),
            "territories": [{"id": t.get("territoryid"), "name": t.get("name")} for t in territories],
            "account_count": len(accounts),
            "accounts": accounts
        }
        
    except Exception as e:
        logger.exception("Error getting accounts for territories")
        return {"success": False, "error": str(e)}