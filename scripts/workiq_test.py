"""
WorkIQ Integration Tests for NoteHelper

Tests various WorkIQ queries that would be useful for auto-populating call logs.
Run these to verify WorkIQ is working and see what data we can extract.
"""

import subprocess
import json
import sys


def run_workiq_query(question: str) -> str:
    """Run a WorkIQ query and return the response."""
    result = subprocess.run(
        ["npx", "-y", "@microsoft/workiq", "ask", "-q", question],
        capture_output=True,
        text=True,
        timeout=120
    )
    return result.stdout + result.stderr


def test_basic_connectivity():
    """Test 1: Basic connectivity - can we query meetings?"""
    print("=" * 60)
    print("TEST 1: Basic Connectivity - Today's Meetings")
    print("=" * 60)
    
    response = run_workiq_query("List my meetings for today with just the title and time")
    print(response)
    return "meeting" in response.lower() or "Meeting" in response


def test_recent_customer_meetings():
    """Test 2: Query recent external customer meetings."""
    print("\n" + "=" * 60)
    print("TEST 2: Recent Customer Meetings (last 7 days)")
    print("=" * 60)
    
    response = run_workiq_query(
        "List my meetings from the last 7 days that had external attendees. "
        "For each, show: meeting title, date, and the external company name if apparent."
    )
    print(response)
    return len(response) > 100


def test_meeting_summary():
    """Test 3: Get a meeting summary that could populate a call log."""
    print("\n" + "=" * 60)
    print("TEST 3: Meeting Summary for Call Log")
    print("=" * 60)
    
    response = run_workiq_query(
        "For my most recent external customer meeting that has a transcript or summary, "
        "please provide: "
        "1) Meeting title and date "
        "2) External company name "
        "3) A 250-word summary of what was discussed "
        "4) Any action items or next steps "
        "Format this in a structured way."
    )
    print(response)
    return len(response) > 100


def test_specific_date_meetings():
    """Test 4: Query meetings for a specific date (for calendar integration)."""
    print("\n" + "=" * 60)
    print("TEST 4: Specific Date Meeting Query")
    print("=" * 60)
    
    response = run_workiq_query(
        "What external customer meetings did I have on February 12, 2026? "
        "Include the meeting title, time, and attendees."
    )
    print(response)
    return len(response) > 50


def test_transcript_extraction():
    """Test 5: Extract structured data from a meeting transcript."""
    print("\n" + "=" * 60)
    print("TEST 5: Transcript Data Extraction")
    print("=" * 60)
    
    response = run_workiq_query(
        "From my most recent customer meeting with a detailed transcript, extract: "
        "1) Technologies or products discussed (Azure services, SQL, etc.) "
        "2) Customer pain points or challenges mentioned "
        "3) Proposed solutions or recommendations "
        "4) Follow-up commitments made "
        "Return this as structured data."
    )
    print(response)
    return len(response) > 100


def test_attendee_info():
    """Test 6: Get attendee details for mapping to NoteHelper sellers."""
    print("\n" + "=" * 60)
    print("TEST 6: Meeting Attendee Information")
    print("=" * 60)
    
    response = run_workiq_query(
        "For my last 3 external customer meetings, list: "
        "1) Meeting title "
        "2) All Microsoft attendees (names and roles if available) "
        "3) All external attendees (names and company)"
    )
    print(response)
    return len(response) > 100


if __name__ == "__main__":
    print("WorkIQ Integration Test Suite for NoteHelper")
    print("=" * 60)
    print("Testing WorkIQ connectivity and data extraction capabilities...")
    print()
    
    tests = [
        ("Basic Connectivity", test_basic_connectivity),
        ("Recent Customer Meetings", test_recent_customer_meetings),
        ("Meeting Summary", test_meeting_summary),
        ("Specific Date Query", test_specific_date_meetings),
        ("Transcript Extraction", test_transcript_extraction),
        ("Attendee Info", test_attendee_info),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, "PASS" if passed else "FAIL"))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((name, "ERROR"))
    
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    for name, status in results:
        print(f"  {name}: {status}")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS FOR INTEGRATION")
    print("=" * 60)
    print("""
If all tests pass, we can integrate WorkIQ with NoteHelper by:

1. Adding WorkIQ MCP server to VS Code settings
2. Creating a "Import from Meeting" button on the call log form
3. Auto-matching meeting attendees to NoteHelper customers
4. Pre-populating call log content from meeting transcripts
5. Auto-suggesting topics based on technologies discussed

The MCP server mode will allow Claude/Copilot to query WorkIQ
directly during call log creation.
""")
