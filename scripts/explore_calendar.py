"""
Explore Microsoft Graph Calendar API access using various auth approaches.
Goal: Find a way to access calendar events and meeting transcripts.
"""
import subprocess
import requests
import json
import sys
from datetime import datetime, timedelta

TENANT_ID = '72f988bf-86f1-41af-91ab-2d7cd011db47'
GRAPH_BASE = 'https://graph.microsoft.com/v1.0'

# Microsoft Graph PowerShell app ID (has broad Graph permissions pre-consented)
GRAPH_PS_CLIENT_ID = '14d82eec-204b-4c2f-b7e8-296a70dab67e'


def get_token_via_browser(scopes):
    """Get token via browser-based auth (passes device compliance like az login)."""
    from msal import PublicClientApplication
    
    app = PublicClientApplication(
        GRAPH_PS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    
    # Browser-based auth - should pass device compliance
    result = app.acquire_token_interactive(
        scopes=scopes,
        prompt="select_account"
    )
    
    if "access_token" in result:
        return result["access_token"]
    else:
        raise RuntimeError(f"Auth failed: {result.get('error_description', result)}")


def decode_token_scopes(token):
    """Decode JWT to see what scopes are included."""
    import base64
    
    # Get the payload (middle part)
    parts = token.split('.')
    if len(parts) != 3:
        return []
    
    payload = parts[1]
    # Add padding
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += '=' * padding
    
    try:
        decoded = base64.b64decode(payload)
        claims = json.loads(decoded)
        return claims.get('scp', '').split() or claims.get('roles', [])
    except:
        return []


def test_calendar_access(token):
    """Test what calendar data we can access."""
    headers = {'Authorization': f'Bearer {token}'}
    
    # Test basic profile
    print("\n=== Testing Profile Access ===")
    r = requests.get(f'{GRAPH_BASE}/me', headers=headers)
    print(f"Profile: {r.status_code}")
    if r.ok:
        me = r.json()
        print(f"  User: {me.get('displayName')} ({me.get('mail')})")
    
    # Test calendar events
    print("\n=== Testing Calendar Access ===")
    now = datetime.utcnow()
    start = (now - timedelta(days=7)).strftime('%Y-%m-%dT00:00:00Z')
    end = (now + timedelta(days=7)).strftime('%Y-%m-%dT23:59:59Z')
    
    r = requests.get(
        f'{GRAPH_BASE}/me/calendarView',
        headers=headers,
        params={
            'startDateTime': start,
            'endDateTime': end,
            '$select': 'subject,start,end,isOnlineMeeting,onlineMeeting,attendees',
            '$orderby': 'start/dateTime',
            '$top': 10
        }
    )
    print(f"Calendar: {r.status_code}")
    
    if r.ok:
        events = r.json().get('value', [])
        print(f"  Found {len(events)} events in past/next 7 days")
        
        teams_meetings = []
        for event in events:
            subject = event.get('subject', 'No subject')
            start_time = event.get('start', {}).get('dateTime', '')[:16]
            is_online = event.get('isOnlineMeeting', False)
            online_meeting = event.get('onlineMeeting')
            
            print(f"  - {start_time}: {subject[:50]}")
            print(f"    Online: {is_online}, Has meeting info: {online_meeting is not None}")
            
            if online_meeting:
                teams_meetings.append({
                    'subject': subject,
                    'joinUrl': online_meeting.get('joinUrl'),
                })
        
        return teams_meetings
    else:
        print(f"  Error: {r.text[:500]}")
        return []


def test_online_meetings(token, join_url=None):
    """Test access to online meetings (for transcripts)."""
    headers = {'Authorization': f'Bearer {token}'}
    
    print("\n=== Testing Online Meetings Access ===")
    
    # Try to list user's online meetings (no $top - not supported)
    r = requests.get(
        f'{GRAPH_BASE}/me/onlineMeetings',
        headers=headers
    )
    print(f"Online Meetings list: {r.status_code}")
    
    if r.ok:
        meetings = r.json().get('value', [])
        print(f"  Found {len(meetings)} online meetings")
        for m in meetings[:3]:
            print(f"  - {m.get('subject', 'No subject')}: {m.get('id', '')[:20]}...")
            
            # Try to get transcripts for this meeting
            meeting_id = m.get('id')
            if meeting_id:
                tr = requests.get(
                    f'{GRAPH_BASE}/me/onlineMeetings/{meeting_id}/transcripts',
                    headers=headers
                )
                print(f"    Transcripts: {tr.status_code}")
                if tr.ok:
                    transcripts = tr.json().get('value', [])
                    print(f"    Found {len(transcripts)} transcripts")
    else:
        print(f"  Error: {r.text[:500]}")


def main():
    print("Exploring Microsoft Graph Calendar/Meeting access...")
    print("=" * 60)
    print("\nUsing browser-based auth (passes device compliance)")
    print("A browser window will open - sign in with your Microsoft account")
    print("-" * 60)
    
    scopes = [
        'User.Read',
        'Calendars.Read',
        'OnlineMeetings.Read'
    ]
    
    try:
        token = get_token_via_browser(scopes)
        print("Got token via browser auth!")
        
        # Decode and show scopes
        scopes_in_token = decode_token_scopes(token)
        print(f"\nToken scopes: {scopes_in_token}")
        
        test_calendar_access(token)
        test_online_meetings(token)
        
    except Exception as e:
        print(f"Failed: {e}")
        raise


if __name__ == '__main__':
    main()
