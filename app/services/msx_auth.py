"""
MSX (Dynamics 365) Authentication Service using Azure CLI.

This module handles authentication to Microsoft Sales Experience (MSX) CRM
using az login tokens. It provides:
- Token acquisition via `az account get-access-token`
- Token caching to avoid repeated CLI calls
- Background refresh to keep tokens fresh
- Status checking for the admin panel

Usage:
    from app.services.msx_auth import get_msx_token, get_msx_auth_status, start_token_refresh_job

Prerequisites:
    - Azure CLI installed and in PATH
    - User must be logged in via `az login`
    - User must have access to Microsoft's corporate tenant
"""

import subprocess
import json
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# CRM constants
CRM_RESOURCE = "https://microsoftsales.crm.dynamics.com"
CRM_BASE_URL = "https://microsoftsales.crm.dynamics.com/api/data/v9.2"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"  # Microsoft corporate tenant

# Token cache
_token_cache: Dict[str, Any] = {
    "access_token": None,
    "expires_on": None,
    "user": None,
    "last_refresh": None,
    "error": None,
}

# Refresh job control
_refresh_thread: Optional[threading.Thread] = None
_refresh_running = False


def _run_az_command() -> Dict[str, Any]:
    """
    Run az account get-access-token to get a fresh CRM token.
    
    Returns:
        Dict with accessToken, expiresOn, and other az CLI output fields.
        
    Raises:
        RuntimeError: If az CLI fails or is not installed.
    """
    cmd = [
        "az", "account", "get-access-token",
        "--resource", CRM_RESOURCE,
        "--tenant", TENANT_ID,
        "--output", "json"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error from az CLI"
            # Common errors
            if "AADSTS" in error_msg:
                raise RuntimeError(f"Azure AD error: {error_msg}")
            if "az login" in error_msg.lower() or "please run" in error_msg.lower():
                raise RuntimeError("Not logged in. Run 'az login' in a terminal first.")
            if "not recognized" in error_msg.lower() or "not found" in error_msg.lower():
                raise RuntimeError("Azure CLI not installed or not in PATH.")
            raise RuntimeError(f"az CLI error: {error_msg}")
        
        return json.loads(result.stdout)
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("az CLI timed out after 30 seconds")
    except FileNotFoundError:
        raise RuntimeError("Azure CLI not installed or not in PATH. Install from https://aka.ms/installazurecli")
    except json.JSONDecodeError:
        raise RuntimeError("Invalid JSON response from az CLI")


def _parse_expiry(expires_on: str) -> datetime:
    """Parse the expiresOn field from az CLI output."""
    # az CLI returns ISO format like "2024-01-15 10:30:00.000000"
    try:
        # Try parsing with microseconds
        return datetime.fromisoformat(expires_on.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError:
        # Try without microseconds
        try:
            return datetime.strptime(expires_on, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            # Fallback: assume it expires in 1 hour
            return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def refresh_token() -> bool:
    """
    Refresh the MSX token by calling az CLI.
    
    Returns:
        True if refresh succeeded, False otherwise.
    """
    global _token_cache
    
    try:
        result = _run_az_command()
        
        _token_cache = {
            "access_token": result.get("accessToken"),
            "expires_on": _parse_expiry(result.get("expiresOn", "")),
            "user": result.get("subscription", "Unknown"),
            "last_refresh": datetime.now(timezone.utc),
            "error": None,
        }
        
        logger.info(f"MSX token refreshed, expires at {_token_cache['expires_on']}")
        return True
        
    except RuntimeError as e:
        _token_cache["error"] = str(e)
        _token_cache["last_refresh"] = datetime.now(timezone.utc)
        logger.warning(f"MSX token refresh failed: {e}")
        return False


def get_msx_token() -> Optional[str]:
    """
    Get a valid MSX access token.
    
    Returns:
        The access token string, or None if not authenticated.
        
    Note:
        This will attempt to refresh if the token is expired or missing.
    """
    global _token_cache
    
    # Check if we have a valid cached token
    if _token_cache["access_token"]:
        now = datetime.now(timezone.utc)
        expires_on = _token_cache["expires_on"]
        
        # If token has > 5 minutes remaining, use it
        if expires_on and (expires_on - now).total_seconds() > 300:
            return _token_cache["access_token"]
    
    # Need to refresh
    if refresh_token():
        return _token_cache["access_token"]
    
    return None


def get_msx_auth_status() -> Dict[str, Any]:
    """
    Get current MSX authentication status for displaying in the UI.
    
    Returns:
        Dict with:
        - authenticated: bool
        - user: str or None
        - expires_on: datetime or None
        - expires_in_minutes: int or None
        - last_refresh: datetime or None
        - error: str or None
        - refresh_job_running: bool
    """
    global _token_cache, _refresh_running
    
    now = datetime.now(timezone.utc)
    expires_on = _token_cache.get("expires_on")
    
    status = {
        "authenticated": False,
        "user": _token_cache.get("user"),
        "expires_on": expires_on,
        "expires_in_minutes": None,
        "last_refresh": _token_cache.get("last_refresh"),
        "error": _token_cache.get("error"),
        "refresh_job_running": _refresh_running,
    }
    
    if _token_cache.get("access_token") and expires_on:
        remaining = (expires_on - now).total_seconds()
        if remaining > 0:
            status["authenticated"] = True
            status["expires_in_minutes"] = int(remaining / 60)
    
    return status


def start_token_refresh_job(interval_seconds: int = 300):
    """
    Start a background thread that refreshes the MSX token periodically.
    
    Args:
        interval_seconds: How often to check/refresh (default 5 minutes).
                         Token will only be refreshed if < 10 minutes remaining.
    """
    global _refresh_thread, _refresh_running
    
    if _refresh_running:
        logger.info("MSX token refresh job already running")
        return
    
    def _refresh_loop():
        global _refresh_running
        _refresh_running = True
        logger.info(f"MSX token refresh job started (interval: {interval_seconds}s)")
        
        while _refresh_running:
            try:
                # Check if token needs refresh (< 10 minutes remaining)
                expires_on = _token_cache.get("expires_on")
                if expires_on:
                    now = datetime.now(timezone.utc)
                    remaining = (expires_on - now).total_seconds()
                    
                    if remaining < 600:  # Less than 10 minutes
                        logger.info("MSX token expiring soon, refreshing...")
                        refresh_token()
                else:
                    # No token cached, try to get one
                    refresh_token()
                    
            except Exception as e:
                logger.error(f"Error in MSX token refresh job: {e}")
            
            # Sleep in small increments so we can stop quickly
            for _ in range(interval_seconds):
                if not _refresh_running:
                    break
                time.sleep(1)
        
        logger.info("MSX token refresh job stopped")
    
    _refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    _refresh_thread.start()


def stop_token_refresh_job():
    """Stop the background token refresh job."""
    global _refresh_running
    _refresh_running = False
    logger.info("MSX token refresh job stop requested")


def clear_token_cache():
    """Clear the cached token (forces re-authentication on next request)."""
    global _token_cache
    _token_cache = {
        "access_token": None,
        "expires_on": None,
        "user": None,
        "last_refresh": None,
        "error": None,
    }
    logger.info("MSX token cache cleared")
