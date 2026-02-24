"""
WorkIQ to NoteHelper Integration Script

This script demonstrates how to query WorkIQ for meeting data
and format it for importing into NoteHelper call logs.

Usage:
    python workiq_import.py --date 2026-02-10
    python workiq_import.py --customer "Customers Bank"
    python workiq_import.py --recent 7
"""

import subprocess
import argparse
import json
import re
from datetime import datetime, timedelta


def query_workiq(question: str) -> str:
    """Run a WorkIQ query and return the response."""
    import sys
    import platform
    
    # Use shell=True on Windows to find npx in PATH
    use_shell = platform.system() == 'Windows'
    
    cmd = f'npx -y @microsoft/workiq ask -q "{question}"' if use_shell else \
          ["npx", "-y", "@microsoft/workiq", "ask", "-q", question]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        shell=use_shell
    )
    return result.stdout


def get_meetings_for_date(date_str: str) -> str:
    """Get all external customer meetings for a specific date."""
    question = f"""
    List all my meetings on {date_str} that had external (non-Microsoft) attendees.
    For each meeting, provide in a consistent format:
    - Meeting Title
    - Start Time
    - Customer/Company Name (the external organization)
    - External Attendees (names)
    - Microsoft Attendees (names)
    """
    return query_workiq(question)


def get_meeting_for_call_log(meeting_title: str, date_str: str = None) -> dict:
    """
    Get detailed meeting information formatted for NoteHelper call log.
    
    Returns a dict with:
    - date: Call date (YYYY-MM-DD)
    - customer: Customer name
    - content: Call notes (summary + action items)
    - topics: List of technologies discussed
    """
    date_context = f"on {date_str}" if date_str else "most recent"
    
    question = f"""
    For the meeting "{meeting_title}" {date_context}, provide the following in a structured format:
    
    DATE: (format as YYYY-MM-DD)
    CUSTOMER: (the external company name)
    SUMMARY: (approximately 250 words describing what was discussed, key points, and outcomes)
    TECHNOLOGIES: (comma-separated list of Azure/Microsoft technologies mentioned)
    ACTION_ITEMS: (numbered list of follow-up items)
    
    Be factual, only include what was explicitly discussed.
    """
    
    response = query_workiq(question)
    
    # Parse the response (basic parsing - would need refinement for production)
    result = {
        'raw_response': response,
        'date': '',
        'customer': '',
        'content': '',
        'topics': []
    }
    
    # Try to extract structured data
    lines = response.split('\n')
    current_section = None
    
    for line in lines:
        line = line.strip()
        if line.startswith('DATE:'):
            result['date'] = line.replace('DATE:', '').strip()
        elif line.startswith('CUSTOMER:'):
            result['customer'] = line.replace('CUSTOMER:', '').strip()
        elif line.startswith('SUMMARY:'):
            result['content'] = line.replace('SUMMARY:', '').strip()
            current_section = 'summary'
        elif line.startswith('TECHNOLOGIES:'):
            tech_str = line.replace('TECHNOLOGIES:', '').strip()
            result['topics'] = [t.strip() for t in tech_str.split(',') if t.strip()]
        elif line.startswith('ACTION_ITEMS:'):
            current_section = 'actions'
        elif current_section == 'actions' and line:
            result['content'] += f"\n\n**Action Items:**\n{line}"
    
    return result


def get_recent_customer_meetings(days: int = 7) -> str:
    """Get recent meetings with external customers."""
    question = f"""
    List my meetings from the last {days} days that had external (non-Microsoft) attendees.
    Group by customer/company. For each meeting show:
    - Date and time
    - Meeting title
    - Whether a transcript/recording is available
    """
    return query_workiq(question)


def format_for_notehelper(meeting_data: dict) -> dict:
    """
    Format meeting data for NoteHelper API.
    
    This would be used to POST to /call-log/new with form data.
    """
    # Map WorkIQ topics to likely NoteHelper topic matches
    topic_mapping = {
        'SQL Server': 'SQL Server',
        'Azure SQL': 'Azure SQL Database',
        'Azure SQL Managed Instance': 'Azure SQL Managed Instance',
        'Azure Virtual Machines': 'Azure VMs',
        'Azure AI': 'Azure AI',
        'Azure OpenAI': 'Azure OpenAI',
        'Fabric': 'Microsoft Fabric',
        'Power BI': 'Power BI',
        'Synapse': 'Azure Synapse',
        'Databricks': 'Azure Databricks',
        'Cosmos DB': 'Azure Cosmos DB',
    }
    
    mapped_topics = []
    for topic in meeting_data.get('topics', []):
        for key, value in topic_mapping.items():
            if key.lower() in topic.lower():
                mapped_topics.append(value)
                break
    
    return {
        'call_date': meeting_data.get('date', ''),
        'customer_name': meeting_data.get('customer', ''),
        'content': meeting_data.get('content', ''),
        'suggested_topics': list(set(mapped_topics)),
        'raw_topics': meeting_data.get('topics', []),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Import meetings from WorkIQ to NoteHelper')
    parser.add_argument('--date', help='Get meetings for a specific date (YYYY-MM-DD)')
    parser.add_argument('--customer', help='Get recent meetings with a specific customer')
    parser.add_argument('--recent', type=int, default=7, help='Get meetings from last N days')
    parser.add_argument('--meeting', help='Get details for a specific meeting title')
    
    args = parser.parse_args()
    
    if args.meeting:
        print("Fetching meeting details for call log import...")
        print("=" * 60)
        data = get_meeting_for_call_log(args.meeting, args.date)
        print("\n[RAW WORKIQ RESPONSE]")
        print(data['raw_response'])
        print("\n[PARSED FOR NOTEHELPER]")
        notehelper_data = format_for_notehelper(data)
        print(json.dumps(notehelper_data, indent=2))
    elif args.date:
        print(f"Meetings on {args.date}:")
        print("=" * 60)
        print(get_meetings_for_date(args.date))
    else:
        print(f"Recent customer meetings (last {args.recent} days):")
        print("=" * 60)
        print(get_recent_customer_meetings(args.recent))
