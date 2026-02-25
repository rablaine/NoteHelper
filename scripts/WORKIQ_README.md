# WorkIQ Integration for NoteHelper

## Status: ✅ WORKING

WorkIQ is installed, authenticated, and working with your Microsoft 365 account.

## What We Verified

1. **Meeting Access** - ✅ Can query today's meetings
2. **Meeting Details** - ✅ Can get meeting title, date, attendees  
3. **Transcript Access** - ✅ Can access meeting transcripts and summaries
4. **Technology Extraction** - ✅ Can identify Azure/Microsoft technologies discussed
5. **Action Items** - ✅ Can extract follow-up items from meetings

## Sample Queries That Work

```bash
# List today's meetings
npx -y @microsoft/workiq ask -q "What meetings do I have today?"

# Get meeting summary for a specific meeting
npx -y @microsoft/workiq ask -q "Summarize my most recent customer meeting"

# Get structured data for call log import
npx -y @microsoft/workiq ask -q "For the 'Customer X' meeting on Feb 10, give me: date, customer name, summary, technologies discussed, action items"
```

## Integration Options

### Option 1: MCP Server in VS Code (Recommended)

Add to your MCP settings (see `workiq_mcp_config.json`):

```json
{
  "workiq": {
    "command": "npx",
    "args": ["-y", "@microsoft/workiq", "mcp"]
  }
}
```

Then ask Claude/Copilot:
- "What customer meetings did I have today?"
- "Create a call log for my Customers Bank meeting from Feb 10"

### Option 2: Python Script Integration

Use `workiq_import.py` to query meetings and format for NoteHelper:

```bash
python scripts/workiq_import.py --date 2026-02-10
python scripts/workiq_import.py --meeting "Meeting Title"
```

### Option 3: Direct Integration in NoteHelper UI

Add an "Import from Meeting" button that:
1. Shows recent meetings from WorkIQ
2. User selects a meeting
3. Auto-populates call log with:
   - Customer name (from external attendees)
   - Call date (from meeting date)
   - Content (from transcript summary)
   - Topics (from technologies mentioned)

## Data Available from WorkIQ

| Field | NoteHelper Mapping |
|-------|-------------------|
| Meeting date | Call date |
| External company name | Customer |
| Meeting summary | Call notes |
| Technologies discussed | Topics |
| Action items | Appended to call notes |
| Microsoft attendees | Seller (match by name) |

## Next Steps

1. Set up WorkIQ MCP server in VS Code settings
2. Add "Import from Meeting" feature to call log form
3. Create customer matching logic (company name → NoteHelper customer)
4. Add topic auto-suggestion based on technologies mentioned

## Files Created

- `scripts/workiq_test.py` - Test suite for WorkIQ queries
- `scripts/workiq_import.py` - Import helper script
- `scripts/workiq_mcp_config.json` - MCP server configuration
