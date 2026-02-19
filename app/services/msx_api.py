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