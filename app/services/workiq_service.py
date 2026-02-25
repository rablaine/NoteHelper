"""
WorkIQ Integration Service

Handles querying WorkIQ for meeting data and transcript summaries.
Uses the npx-based WorkIQ CLI tool.
"""
import subprocess
import platform
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def fuzzy_match_score(text1: str, text2: str) -> float:
    """
    Calculate fuzzy match score between two strings.
    Returns a value between 0.0 and 1.0.
    """
    if not text1 or not text2:
        return 0.0
    
    # Normalize for comparison: lowercase and remove common words
    def normalize(s):
        s = s.lower().strip()
        # Remove common suffixes/words that don't help matching
        for word in ['inc', 'inc.', 'llc', 'corp', 'corporation', 'ltd', 'company', 'co']:
            s = s.replace(word, '')
        return s.strip()
    
    t1 = normalize(text1)
    t2 = normalize(text2)
    
    # Direct substring check (more generous)
    if t1 in t2 or t2 in t1:
        return 0.9
    
    # Use SequenceMatcher for fuzzy ratio
    return SequenceMatcher(None, t1, t2).ratio()


def query_workiq(question: str, timeout: int = 120) -> str:
    """
    Run a WorkIQ query and return the response.
    
    Args:
        question: The natural language question to ask WorkIQ
        timeout: Maximum seconds to wait for response
        
    Returns:
        The text response from WorkIQ
        
    Raises:
        TimeoutError: If query takes longer than timeout
        RuntimeError: If WorkIQ query fails
    """
    import shutil
    import os
    
    is_windows = platform.system() == 'Windows'
    
    # Find npx executable
    npx_path = shutil.which('npx')
    if not npx_path and is_windows:
        for path in [
            os.path.expandvars(r'%APPDATA%\npm\npx.cmd'),
            os.path.expandvars(r'%ProgramFiles%\nodejs\npx.cmd'),
        ]:
            if os.path.exists(path):
                npx_path = path
                break
    
    if not npx_path:
        raise RuntimeError("npx not found. Please install Node.js.")
    
    logger.info(f"Querying WorkIQ: {question[:100]}...")
    
    try:
        if is_windows:
            # On Windows, use PowerShell to avoid cmd.exe escaping issues
            # PowerShell handles special characters in strings properly
            # Escape single quotes by doubling them (PowerShell string escape)
            escaped_q = question.replace("'", "''")
            
            # Build PowerShell command
            ps_cmd = f"& '{npx_path}' -y @microsoft/workiq ask -q '{escaped_q}'"
            
            cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
            logger.info(f"Running PowerShell command for WorkIQ...")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False
            )
        else:
            # On Unix, list format works perfectly
            cmd = [npx_path, "-y", "@microsoft/workiq", "ask", "-q", question]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False
            )
        
        if result.returncode != 0:
            logger.error(f"WorkIQ error: {result.stderr}")
            raise RuntimeError(f"WorkIQ query failed: {result.stderr}")
        
        logger.info(f"WorkIQ response received ({len(result.stdout)} chars)")
        return result.stdout
        
    except subprocess.TimeoutExpired:
        logger.error(f"WorkIQ query timed out after {timeout}s")
        raise TimeoutError(f"WorkIQ query timed out after {timeout} seconds")


def get_meetings_for_date(date_str: str) -> List[Dict[str, Any]]:
    """
    Get all external customer meetings for a specific date.
    
    Args:
        date_str: Date in YYYY-MM-DD format
        
    Returns:
        List of meeting dicts with keys:
        - id: Unique identifier (derived from title + time)
        - title: Meeting title
        - start_time: Meeting start time as datetime
        - customer: Extracted customer/company name
        - attendees: List of attendee names
    """
    question = f"List all my meetings on {date_str} with external attendees. Include meeting title, time, and company name."
    
    try:
        response = query_workiq(question)
        logger.info(f"WorkIQ raw response length: {len(response)}, first 200 chars: {response[:200]}")
        meetings = _parse_meetings_response(response, date_str)
        logger.info(f"Parsed {len(meetings)} meetings from response")
        return meetings
    except Exception as e:
        logger.error(f"Failed to get meetings for {date_str}: {e}")
        return []


def _parse_meetings_response(response: str, date_str: str) -> List[Dict[str, Any]]:
    """Parse WorkIQ meeting list response into structured data.
    
    Handles WorkIQ's markdown table format like:
    | Time | Meeting Title | External Company |
    | 11:00 AM - 11:30 AM | **Fabric Meeting - CCFI** | CCFI |
    
    Also handles numbered list format:
    1. **Meeting Title**
       **9:00 AM** · Organizer: Name
    """
    meetings = []
    
    if not response or 'no meetings' in response.lower():
        return meetings
    
    # Try table format first (most common from WorkIQ)
    # Look for lines that start with | and contain times
    time_pattern = re.compile(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', re.IGNORECASE)
    
    for line in response.split('\n'):
        line = line.strip()
        
        # Skip header row or separator rows
        if not line.startswith('|') or '---' in line or 'Time' in line and 'Meeting' in line:
            continue
        
        # Split carefully on unescaped pipes
        # Replace escaped pipes temporarily
        temp = line.replace('\\|', '\x00')
        parts = [p.replace('\x00', '|').strip() for p in temp.split('|')]
        
        # Filter empty parts (from leading/trailing pipes)
        parts = [p for p in parts if p]
        
        # Need at least time and title
        if len(parts) < 2:
            continue
        
        # Find which part has the time
        time_col = None
        time_str = None
        for i, part in enumerate(parts):
            match = time_pattern.search(part)
            if match:
                time_col = i
                time_str = match.group(1)
                break
        
        if time_str is None:
            continue
        
        # Title is usually in the next column, company after that
        title = parts[time_col + 1] if len(parts) > time_col + 1 else ''
        company = parts[time_col + 2] if len(parts) > time_col + 2 else ''
        
        # Clean up title - remove bold markers
        title = title.strip('* ')
        company = company.strip('* ')
        
        meeting = {
            'id': '',
            'title': title,
            'start_time': None,
            'start_time_str': time_str,
            'customer': company,
            'attendees': []
        }
        
        # Parse time
        try:
            time_obj = datetime.strptime(time_str, '%I:%M %p').time()
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            meeting['start_time'] = datetime.combine(date_obj, time_obj)
        except ValueError as e:
            logger.warning(f"Could not parse time '{time_str}': {e}")
        
        # Generate ID
        id_base = f"{date_str}_{title}_{time_str}"
        meeting['id'] = re.sub(r'[^a-zA-Z0-9_]', '', id_base.replace(' ', '_'))[:50]
        meetings.append(meeting)
    
    if meetings:
        logger.info(f"Parsed {len(meetings)} meetings from WorkIQ table format")
        return meetings
    
    # Fallback: try numbered list format
    # Pattern to match: "1. **Meeting Title**"
    title_pattern = re.compile(r'(?:^|\n)\s*(?:\d+\.|-)\s*\*\*([^*]+)\*\*', re.MULTILINE)
    time_pattern = re.compile(r'\*?\*?(\d{1,2}:\d{2})\s*(?:-\s*\d{1,2}:\d{2})?\s*(AM|PM)?\*?\*?', re.IGNORECASE)
    
    sections = re.split(r'\n(?=\s*\d+\.)', response)
    
    for section in sections:
        if not section.strip():
            continue
        
        title_match = title_pattern.search(section)
        if not title_match:
            continue
            
        title = title_match.group(1).strip()
        
        meeting = {
            'id': '',
            'title': title,
            'start_time': None,
            'start_time_str': '',
            'customer': '',
            'attendees': []
        }
        
        time_match = time_pattern.search(section)
        if time_match:
            time_str = time_match.group(1)
            am_pm = time_match.group(2) or ''
            meeting['start_time_str'] = f"{time_str} {am_pm}".strip()
            
            try:
                if am_pm:
                    time_obj = datetime.strptime(f"{time_str} {am_pm}", '%I:%M %p').time()
                else:
                    time_obj = datetime.strptime(time_str, '%H:%M').time()
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                meeting['start_time'] = datetime.combine(date_obj, time_obj)
            except ValueError as e:
                logger.warning(f"Could not parse time '{time_str} {am_pm}': {e}")
        
        # Extract customer from title
        if '|' in title:
            meeting['customer'] = title.split('|')[0].strip()
        elif ' - ' in title:
            meeting['customer'] = title.split(' - ')[0].strip()
        
        id_base = f"{date_str}_{title}_{meeting['start_time_str']}"
        meeting['id'] = re.sub(r'[^a-zA-Z0-9_]', '', id_base.replace(' ', '_'))[:50]
        meetings.append(meeting)
    
    logger.info(f"Parsed {len(meetings)} meetings from WorkIQ list format")
    return meetings


def find_best_customer_match(meetings: List[Dict[str, Any]], customer_name: str) -> Optional[int]:
    """
    Find the best matching meeting for a customer name.
    
    Args:
        meetings: List of meeting dicts from get_meetings_for_date
        customer_name: Customer name to match against
        
    Returns:
        Index of best matching meeting, or None if no good match (score < 0.5)
    """
    if not meetings or not customer_name:
        return None
    
    best_score = 0.0
    best_index = None
    
    for i, meeting in enumerate(meetings):
        # Check against meeting title and customer fields
        title_score = fuzzy_match_score(customer_name, meeting.get('title', ''))
        customer_score = fuzzy_match_score(customer_name, meeting.get('customer', ''))
        
        # Take the better match
        score = max(title_score, customer_score)
        
        if score > best_score:
            best_score = score
            best_index = i
    
    # Only return if score is decent (> 0.5)
    if best_score >= 0.5:
        logger.info(f"Fuzzy matched '{customer_name}' to meeting {best_index} with score {best_score:.2f}")
        return best_index
    
    return None


def get_meeting_summary(meeting_title: str, date_str: str = None) -> Dict[str, Any]:
    """
    Get a detailed 250-word summary for a specific meeting.
    
    Args:
        meeting_title: The meeting title to summarize
        date_str: Optional date for context (YYYY-MM-DD)
        
    Returns:
        Dict with:
        - summary: The 250-word summary text
        - topics: List of technologies/topics discussed
        - action_items: List of follow-up items
    """
    date_context = f"on {date_str}" if date_str else ""
    
    # Simplified prompt - let WorkIQ format naturally
    question = f'Summarize the meeting "{meeting_title}" {date_context} in approximately 250 words. Include key discussion points, technologies mentioned, and any action items.'
    
    try:
        response = query_workiq(question, timeout=120)
        return _parse_summary_response(response)
    except TimeoutError:
        logger.warning(f"Meeting summary timed out for: {meeting_title}")
        return {
            'summary': "Summary request timed out. The meeting may not have a transcript, or the transcript is still processing.",
            'topics': [],
            'action_items': []
        }
    except Exception as e:
        logger.error(f"Failed to get meeting summary: {e}")
        return {
            'summary': f"Error fetching summary: {str(e)}",
            'topics': [],
            'action_items': []
        }


def _parse_summary_response(response: str) -> Dict[str, Any]:
    """Parse WorkIQ summary response into structured data.
    
    Handles both structured format (SUMMARY:/TECHNOLOGIES:/ACTION_ITEMS:) 
    and natural language responses.
    """
    result = {
        'summary': '',
        'topics': [],
        'action_items': [],
        'raw_response': response
    }
    
    # Check if response has structured format
    has_structured = 'SUMMARY:' in response or 'TECHNOLOGIES:' in response
    
    if not has_structured:
        # Use natural language parsing
        # Remove markdown links [text](url) but keep the text
        clean_response = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', response)
        
        # Remove heading markers
        clean_response = re.sub(r'^#{1,6}\s*', '', clean_response, flags=re.MULTILINE)
        
        # The whole response is the summary  
        result['summary'] = clean_response.strip()
        
        # Try to extract technologies mentioned (common Azure terms)
        azure_terms = re.findall(
            r'\b(Azure[A-Za-z\s]*|Microsoft Fabric|Power BI|SQL Server|Cosmos DB|'
            r'Synapse|Databricks|Data Factory|Logic Apps|Functions|'
            r'App Service|AKS|Kubernetes|Storage|Machine Learning|'
            r'Cognitive Services|OpenAI|AI|ML|ETL|Data Lake|'
            r'DevOps|GitHub|Event Hub|Service Bus|API Management)\b',
            response, re.IGNORECASE
        )
        if azure_terms:
            # Dedupe while preserving order
            seen = set()
            result['topics'] = [t for t in azure_terms if not (t.lower() in seen or seen.add(t.lower()))][:10]
        
        # Try to extract action items (look for "next steps" patterns)
        action_pattern = r'(?:next steps?|action items?|follow[- ]?ups?|to[- ]?do)[:\s]*(?:\n|$)((?:[-•*\d\.]+\s*.+\n?)+)'
        action_match = re.search(action_pattern, response, re.IGNORECASE)
        if action_match:
            items_text = action_match.group(1)
            items = re.findall(r'[-•*\d\.]+\s*(.+)', items_text)
            result['action_items'] = [item.strip() for item in items if item.strip()][:10]
        
        return result
    
    # Original structured parsing
    lines = response.split('\n')
    current_section = None
    current_content = []
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('SUMMARY:'):
            if current_section:
                _save_section(result, current_section, current_content)
            current_section = 'summary'
            content = stripped.replace('SUMMARY:', '').strip()
            current_content = [content] if content else []
            
        elif stripped.startswith('TECHNOLOGIES:'):
            if current_section:
                _save_section(result, current_section, current_content)
            current_section = 'technologies'
            content = stripped.replace('TECHNOLOGIES:', '').strip()
            current_content = [content] if content else []
            
        elif stripped.startswith('ACTION_ITEMS:') or stripped.startswith('ACTION ITEMS:'):
            if current_section:
                _save_section(result, current_section, current_content)
            current_section = 'action_items'
            content = stripped.replace('ACTION_ITEMS:', '').replace('ACTION ITEMS:', '').strip()
            current_content = [content] if content else []
            
        elif current_section and stripped:
            current_content.append(stripped)
    
    if current_section:
        _save_section(result, current_section, current_content)
    
    return result


def _save_section(result: Dict, section: str, content: List[str]):
    """Save parsed section content to result dict."""
    if section == 'summary':
        result['summary'] = ' '.join(content).strip()
    elif section == 'technologies':
        # Parse comma-separated list
        all_text = ' '.join(content)
        topics = [t.strip() for t in all_text.split(',') if t.strip()]
        # Clean up topics
        topics = [re.sub(r'^[-•*]\s*', '', t) for t in topics]
        result['topics'] = topics
    elif section == 'action_items':
        # Parse numbered/bulleted list
        items = []
        for line in content:
            # Remove numbering/bullets
            cleaned = re.sub(r'^[\d\.\)\-•*]+\s*', '', line.strip())
            if cleaned:
                items.append(cleaned)
        result['action_items'] = items
