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


def lookup_account_by_tpid(tpid: str) -> Dict[str, Any]:
    """
    Look up an MSX account by TPID (msp_mstopparentid).
    
    Args:
        tpid: The Top Parent ID to search for.
        
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
        # Build OData query
        url = (
            f"{CRM_BASE_URL}/accounts"
            f"?$filter=msp_mstopparentid eq '{tpid_clean}'"
            f"&$select=accountid,name,msp_mstopparentid"
        )
        
        response = requests.get(
            url,
            headers=_get_headers(token),
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            accounts = data.get("value", [])
            
            result = {
                "success": True,
                "accounts": accounts,
                "count": len(accounts),
            }
            
            # Build MSX URL if exactly one match
            if len(accounts) == 1:
                account_id = accounts[0].get("accountid")
                result["url"] = build_account_url(account_id)
                result["account_name"] = accounts[0].get("name")
            elif len(accounts) > 1:
                # Multiple matches - include URLs for each
                for account in accounts:
                    account["url"] = build_account_url(account.get("accountid"))
            
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
