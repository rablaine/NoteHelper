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

from app.services.msx_auth import get_msx_token, CRM_BASE_URL

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


def test_connection() -> Dict[str, Any]:
    """
    Test the MSX connection by calling WhoAmI.
    
    Returns:
        Dict with:
        - success: bool
        - user_id: str (GUID) if successful
        - error: str if failed
    """
    token = get_msx_token()
    if not token:
        return {"success": False, "error": "Not authenticated. Run 'az login' first."}
    
    try:
        response = requests.get(
            f"{CRM_BASE_URL}/WhoAmI",
            headers=_get_headers(token),
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "user_id": data.get("UserId"),
                "business_unit_id": data.get("BusinessUnitId"),
                "organization_id": data.get("OrganizationId"),
            }
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
    token = get_msx_token()
    if not token:
        return {"success": False, "error": "Not authenticated. Run 'az login' first."}
    
    # Sanitize TPID - should be numeric
    tpid_clean = str(tpid).strip()
    
    try:
        # Build OData query - include parenting level to identify "Top" parent
        url = (
            f"{CRM_BASE_URL}/accounts"
            f"?$filter=msp_mstopparentid eq '{tpid_clean}'"
            f"&$select=accountid,name,msp_mstopparentid,msp_parentinglevelcode"
        )
        
        response = requests.get(
            url,
            headers=_get_headers(token),
            timeout=REQUEST_TIMEOUT
        )
        
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
            # 1. If only one account, use it
            # 2. If customer name matches an account, use that
            # 3. If exactly ONE Top parent, use it
            # 4. Otherwise, don't auto-select (let user choose)
            
            if len(accounts) == 1:
                result["url"] = accounts[0]["url"]
                result["account_name"] = accounts[0]["name"]
            elif name_match:
                # Found matching customer name - use it
                result["url"] = name_match["url"]
                result["account_name"] = name_match["name"]
                result["name_match"] = True
            elif len(top_accounts) == 1:
                # Exactly one Top parent - safe to auto-select
                result["url"] = top_accounts[0]["url"]
                result["account_name"] = top_accounts[0]["name"]
                result["top_parent"] = True
            elif len(top_accounts) > 1:
                # Multiple Top parents - show them for selection
                result["multiple_tops"] = len(top_accounts)
            
            return result
            
        elif response.status_code == 401:
            return {"success": False, "error": "Token expired. Re-authenticate with 'az login'."}
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
