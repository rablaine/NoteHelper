#!/usr/bin/env python3
"""
Explore Microsoft Graph API for calendar events and meeting transcripts.

This script tests what data we can access to auto-populate call logs from
Teams meetings with transcripts.

Prerequisites:
- VPN connected (for corporate tenant)
- msal package: pip install msal

Usage:
    python scripts/explore_calendar_transcripts.py
"""

import subprocess
import json
import requests
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import re

try:
    import msal
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False

GRAPH_RESOURCE = "https://graph.microsoft.com"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Pre-authorized Graph client IDs
# Graph Explorer app ID - pre-authorized for many Graph scopes
GRAPH_EXPLORER_CLIENT_ID = "de8bc8b5-d9f9-48b1-a8ad-b748da725064"

# Try a few known-good client IDs
CLIENT_IDS_TO_TRY = [
    GRAPH_EXPLORER_CLIENT_ID,  # Graph Explorer
    "1950a258-227b-4e31-a9cf-717495945fc2",  # Microsoft Azure PowerShell  
    "04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI
]

# Scopes we need for calendar and meetings
SCOPES = [
    "User.Read",
    "Calendars.Read",
    "OnlineMeetings.Read",
]

# Token cache file
TOKEN_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".graph_token_cache.json")


def get_msal_token():
    """
    Get Graph token using MSAL with interactive login.
    
    This requests the specific scopes we need (Calendars.Read, etc.)
    and caches the token for reuse. Tries multiple pre-authorized app IDs.
    """
    if not MSAL_AVAILABLE:
        raise RuntimeError("msal package not installed. Run: pip install msal")
    
    last_error = None
    
    for client_id in CLIENT_IDS_TO_TRY:
        try:
            # Load token cache (per client)
            cache_file = TOKEN_CACHE_FILE.replace('.json', f'_{client_id[:8]}.json')
            cache = msal.SerializableTokenCache()
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cache.deserialize(f.read())
            
            # Create public client app
            app = msal.PublicClientApplication(
                client_id,
                authority=f"https://login.microsoftonline.com/{TENANT_ID}",
                token_cache=cache
            )
            
            # Try to get token silently first (from cache)
            accounts = app.get_accounts()
            result = None
            
            if accounts:
                result = app.acquire_token_silent(SCOPES, account=accounts[0])
            
            if not result:
                # Need interactive login
                print(f"    Trying client ID: {client_id[:8]}...")
                print("    (Opening browser for authentication)")
                result = app.acquire_token_interactive(scopes=SCOPES)
            
            # Save cache
            if cache.has_state_changed:
                with open(cache_file, 'w') as f:
                    f.write(cache.serialize())
            
            if "access_token" in result:
                return result["access_token"]
            else:
                last_error = result.get("error_description", result.get("error", "Unknown"))
                continue
                
        except Exception as e:
            last_error = str(e)
            continue
    
    raise RuntimeError(f"All client IDs failed. Last error: {last_error}")
    
    if "access_token" in result:
        return result["access_token"]
    else:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Failed to get token: {error}")


def get_graph_token():
    """
    Get Graph API token - tries MSAL first (full permissions), 
    falls back to az CLI (limited permissions).
    """
    if MSAL_AVAILABLE:
        return get_msal_token()
    else:
        print("    Note: msal not installed, using az CLI (limited permissions)")
        print("    For full access, run: pip install msal")
        return get_graph_token_az_cli()


def get_graph_token_az_cli():
    """Get Microsoft Graph API token via az CLI (limited scopes)."""
    cmd = f'az account get-access-token --resource "{GRAPH_RESOURCE}" --tenant "{TENANT_ID}" --output json'
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"az CLI failed: {result.stderr}")
    
    token_data = json.loads(result.stdout)
    return token_data["accessToken"]


def check_basic_access(token):
    """Verify token works by fetching user profile."""
    headers = build_headers(token)
    
    url = f"{GRAPH_BASE_URL}/me"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        return {"success": True, "user": data.get("displayName"), "email": data.get("mail")}
    else:
        return {"success": False, "error": f"{response.status_code}: {response.text[:200]}"}


def build_headers(token):
    """Build headers for Graph API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_calendar_events(token, days_back=14, days_forward=7):
    """
    Fetch calendar events from the past N days to N days in the future.
    
    Returns events with Teams meeting info if available.
    """
    headers = build_headers(token)
    
    # Calculate date range
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
    end_date = (now + timedelta(days=days_forward)).strftime("%Y-%m-%dT23:59:59Z")
    
    url = (
        f"{GRAPH_BASE_URL}/me/calendarView"
        f"?startDateTime={start_date}"
        f"&endDateTime={end_date}"
        f"&$select=id,subject,start,end,attendees,organizer,onlineMeeting,isOnlineMeeting,onlineMeetingUrl,bodyPreview"
        f"&$orderby=start/dateTime desc"
        f"&$top=50"
    )
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Error fetching calendar: {response.status_code}")
        print(response.text)
        return []
    
    data = response.json()
    return data.get("value", [])


def extract_meeting_id_from_url(join_url):
    """
    Extract the online meeting ID from a Teams join URL.
    
    Teams URLs look like:
    https://teams.microsoft.com/l/meetup-join/19%3ameeting_xxx...
    """
    if not join_url:
        return None
    
    # The meeting thread ID is in the URL path
    # We need to decode and extract it
    match = re.search(r'meetup-join/([^/]+)', join_url)
    if match:
        return match.group(1)
    return None


def get_online_meeting_by_join_url(token, join_url):
    """
    Get online meeting details using the join URL.
    
    This uses the /me/onlineMeetings endpoint with a filter.
    """
    headers = build_headers(token)
    
    # URL encode the join URL for the filter
    encoded_url = quote(join_url, safe='')
    
    url = f"{GRAPH_BASE_URL}/me/onlineMeetings?$filter=JoinWebUrl eq '{join_url}'"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"  Error fetching online meeting: {response.status_code}")
        # Try alternate approach - list all and filter
        return None
    
    data = response.json()
    meetings = data.get("value", [])
    return meetings[0] if meetings else None


def list_online_meetings(token):
    """
    List recent online meetings.
    """
    headers = build_headers(token)
    
    url = f"{GRAPH_BASE_URL}/me/onlineMeetings"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Error listing online meetings: {response.status_code}")
        print(response.text)
        return []
    
    data = response.json()
    return data.get("value", [])


def get_meeting_transcripts(token, meeting_id):
    """
    Get transcripts for a specific online meeting.
    
    Note: Requires OnlineMeetingTranscript.Read.All permission.
    """
    headers = build_headers(token)
    
    url = f"{GRAPH_BASE_URL}/me/onlineMeetings/{meeting_id}/transcripts"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 403:
        return {"error": "Permission denied - may need OnlineMeetingTranscript.Read.All"}
    elif response.status_code == 404:
        return {"error": "No transcripts found or meeting not accessible"}
    elif response.status_code != 200:
        return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
    
    data = response.json()
    return data.get("value", [])


def get_transcript_content(token, meeting_id, transcript_id, format="text/vtt"):
    """
    Get the actual transcript content.
    
    Formats:
    - text/vtt: WebVTT format with timestamps
    - text/plain: Plain text (not always available)
    """
    headers = build_headers(token)
    headers["Accept"] = format
    
    url = f"{GRAPH_BASE_URL}/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return f"Error: {response.status_code} - {response.text[:200]}"
    
    return response.text


def parse_vtt_to_text(vtt_content):
    """
    Parse VTT (WebVTT) content into plain text with speaker labels.
    
    VTT format:
    WEBVTT
    
    00:00:05.000 --> 00:00:10.000
    <v Speaker Name>Text they said</v>
    """
    lines = []
    current_speaker = None
    
    for line in vtt_content.split('\n'):
        line = line.strip()
        
        # Skip empty lines and timestamp lines
        if not line or line == 'WEBVTT' or '-->' in line:
            continue
        
        # Extract speaker and text from <v Speaker>Text</v>
        match = re.match(r'<v ([^>]+)>(.+)</v>', line)
        if match:
            speaker = match.group(1)
            text = match.group(2)
            
            if speaker != current_speaker:
                current_speaker = speaker
                lines.append(f"\n**{speaker}:**")
            lines.append(text)
        elif not line.startswith('<'):
            # Plain text line
            lines.append(line)
    
    return ' '.join(lines)


def categorize_attendees(attendees):
    """
    Categorize attendees into internal (Microsoft) and external (customers).
    """
    internal = []
    external = []
    
    for attendee in attendees:
        email = attendee.get("emailAddress", {}).get("address", "")
        name = attendee.get("emailAddress", {}).get("name", "")
        
        if "@microsoft.com" in email.lower():
            internal.append({"name": name, "email": email})
        else:
            external.append({"name": name, "email": email})
    
    return {"internal": internal, "external": external}


def main():
    print("=" * 60)
    print("Calendar & Transcript Explorer")
    print("=" * 60)
    
    # Get token
    print("\n[1] Getting Graph API token...")
    try:
        token = get_graph_token()
        print("    ✓ Token acquired")
    except Exception as e:
        print(f"    ✗ Failed: {e}")
        if MSAL_AVAILABLE:
            print("\n    Try clearing the token cache and re-authenticating:")
            print(f"    del {TOKEN_CACHE_FILE}")
        else:
            print("\n    Install msal for better auth: pip install msal")
        return
    
    # Check basic access first
    print("\n[1b] Verifying Graph API access...")
    access_check = check_basic_access(token)
    if access_check["success"]:
        print(f"    ✓ Logged in as: {access_check['user']} ({access_check['email']})")
    else:
        print(f"    ✗ Cannot access Graph API: {access_check['error']}")
        return
    
    # Fetch calendar events
    print("\n[2] Fetching calendar events (past 14 days, next 7 days)...")
    events = get_calendar_events(token, days_back=14, days_forward=7)
    print(f"    ✓ Found {len(events)} events")
    
    # Filter to Teams meetings with external attendees
    teams_meetings = []
    for event in events:
        is_teams = event.get("isOnlineMeeting", False)
        attendees = event.get("attendees", [])
        categorized = categorize_attendees(attendees)
        
        if is_teams and categorized["external"]:
            teams_meetings.append({
                "event": event,
                "categorized_attendees": categorized
            })
    
    print(f"    ✓ {len(teams_meetings)} are Teams meetings with external attendees")
    
    # Show meetings
    print("\n[3] Teams meetings with external attendees:")
    print("-" * 60)
    
    for i, meeting in enumerate(teams_meetings[:10]):  # Show first 10
        event = meeting["event"]
        attendees = meeting["categorized_attendees"]
        
        start_time = event.get("start", {}).get("dateTime", "")[:16]
        subject = event.get("subject", "No subject")[:50]
        
        external_names = [a["name"] for a in attendees["external"][:3]]
        external_str = ", ".join(external_names)
        if len(attendees["external"]) > 3:
            external_str += f" +{len(attendees['external']) - 3} more"
        
        print(f"\n  [{i+1}] {start_time}")
        print(f"      Subject: {subject}")
        print(f"      External: {external_str}")
        
        # Try to get online meeting info
        join_url = event.get("onlineMeeting", {}).get("joinUrl") or event.get("onlineMeetingUrl")
        if join_url:
            print(f"      Join URL: {join_url[:50]}...")
    
    # Try to access transcripts
    print("\n\n[4] Checking transcript access...")
    print("-" * 60)
    
    # First list online meetings to see what we have access to
    print("\n    Listing online meetings...")
    online_meetings = list_online_meetings(token)
    print(f"    Found {len(online_meetings)} accessible online meetings")
    
    if online_meetings:
        print("\n    Checking for transcripts on first few meetings...")
        
        for meeting in online_meetings[:5]:
            meeting_id = meeting.get("id")
            subject = meeting.get("subject", "No subject")[:40]
            print(f"\n    Meeting: {subject}")
            
            transcripts = get_meeting_transcripts(token, meeting_id)
            
            if isinstance(transcripts, dict) and "error" in transcripts:
                print(f"      ✗ {transcripts['error']}")
            elif transcripts:
                print(f"      ✓ Found {len(transcripts)} transcript(s)!")
                
                # Try to get content of first transcript
                for t in transcripts[:1]:
                    t_id = t.get("id")
                    created = t.get("createdDateTime", "")[:10]
                    print(f"        Transcript from {created}")
                    
                    content = get_transcript_content(token, meeting_id, t_id)
                    if content and not content.startswith("Error"):
                        # Preview first 500 chars
                        plain_text = parse_vtt_to_text(content)
                        print(f"        Preview: {plain_text[:300]}...")
                    else:
                        print(f"        {content}")
            else:
                print(f"      - No transcripts")
    
    # Summary
    print("\n\n[5] Summary & Next Steps")
    print("=" * 60)
    print("""
    Data we can access:
    - Calendar events with subject, date, attendees
    - Categorize attendees as internal vs external (by email domain)
    - Teams meeting IDs and join URLs
    
    For auto-populating call logs:
    1. Show user a list of recent Teams meetings with external attendees
    2. Match external attendee emails/domains to customers in database
    3. If transcript available, offer to summarize with AI
    4. Pre-fill call log form with:
       - Customer (matched from attendees)
       - Date (from meeting)
       - Content (transcript summary or placeholder)
       - Topics (extracted from transcript via AI)
    
    Potential UI flow:
    - New "Import from Calendar" button on call logs page
    - Shows recent external meetings not yet logged
    - Click meeting to create call log with pre-filled data
    - AI summary of transcript if available
    """)


if __name__ == "__main__":
    main()
