"""
Explore Microsoft Graph Calendar API access using device code flow.
Goal: Find a way to access calendar events and meeting transcripts.
"""
import msal
import requests
import json
from datetime import datetime, timedelta

# Microsoft Office app - often has more pre-consent than other apps
OFFICE_APP_ID = 'd3590ed6-52b3-4102-aeff-aad2292ab01c'
TENANT_ID = '72f988bf-86f1-41af-91ab-2d7cd011db47'
GRAPH_BASE = 'https://graph.microsoft.com/v1.0'


def get_token(scopes):
    """Get token using device code flow."""
    app = msal.PublicClientApplication(
        OFFICE_APP_ID,
        authority=f'https://login.microsoftonline.com/{TENANT_ID}'
    )
    
    # Check cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and 'access_token' in result:
            print("Using cached token")
            return result['access_token']
    
    # Device code flow
    flow = app.initiate_device_flow(scopes=scopes)
    if 'user_code' not in flow:
        raise Exception(f"Device flow failed: {flow}")
    
    print(f"\nGo to: {flow['verification_uri']}")
    print(f"Enter code: {flow['user_code']}\n")
    print("Waiting for you to complete sign-in...")
    
    result = app.acquire_token_by_device_flow(flow)
    if 'access_token' in result:
        return result['access_token']
    else:
        raise Exception(f"Token acquisition failed: {result.get('error_description', result)}")


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


def test_online_meetings(token):
    """Test access to online meetings (for transcripts)."""
    headers = {'Authorization': f'Bearer {token}'}
    
    print("\n=== Testing Online Meetings Access ===")
    
    # Try to list user's online meetings
    r = requests.get(
        f'{GRAPH_BASE}/me/onlineMeetings',
        headers=headers,
        params={'$top': 5}
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
    
    # Start with Calendar.Read scope
    scopes = [
        'https://graph.microsoft.com/User.Read',
        'https://graph.microsoft.com/Calendars.Read',
    ]
    
    print(f"Requesting scopes: {scopes}")
    print("-" * 60)
    
    try:
        token = get_token(scopes)
        print("SUCCESS! Got token")
        
        teams_meetings = test_calendar_access(token)
        test_online_meetings(token)
        
    except Exception as e:
        print(f"Failed: {e}")
        if "admin" in str(e).lower() or "consent" in str(e).lower():
            print("\n*** Admin consent required for these scopes ***")
            print("Options:")
            print("1. Ask your admin to consent to Graph Explorer or this app")
            print("2. Try using https://graph.microsoft.com/ in a browser (Graph Explorer)")
            print("3. Use PowerShell: Connect-MgGraph -Scopes 'Calendars.Read'")


if __name__ == '__main__':
    main()
