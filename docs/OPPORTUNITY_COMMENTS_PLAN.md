# Opportunity & Comments Feature Plan

## Overview

Add the ability to view MSX opportunities for a customer and read/write forecast comments on each opportunity — all without leaving NoteHelper.

**Design philosophy:** Opportunities are fetched fresh from MSX on every page load (no local caching). Comments are read and written directly to the MSX `msp_forecastcommentsjsonfield` via PATCH. The only local storage is a lightweight `Opportunity` model to track which opportunities exist per customer (populated during milestone sync, which already has the data).

---

## API Exploration Findings

### Opportunity Entity (`opportunities`)

The explore script queried the MSX API at:
```
GET /api/data/v9.2/opportunities({guid})?$select=...
```

**Key fields discovered:**

| MSX Field | Type | Description |
|-----------|------|-------------|
| `opportunityid` | GUID | Primary key |
| `name` | String | Opportunity name (e.g., "Fabric Opportunity") |
| `msp_opportunitynumber` | String | Display ID (e.g., "7-3FU4Q45URI") |
| `statecode` | OptionSet | 0=Open, 1=Won, 2=Lost |
| `statuscode` | OptionSet | Sub-status |
| `estimatedvalue` | Money | Estimated revenue |
| `estimatedclosedate` | DateTime | Expected close date |
| `_parentaccountid_value` | Lookup | Parent account GUID |
| `_ownerid_value` | Lookup | Owner (seller) |
| `msp_forecastcomments` | Memo | Auto-generated plain text summary of comments |
| `msp_forecastcommentsjsonfield` | Memo (30,000 char max) | **JSON array** of structured comments |
| `msp_forecastcomments_lastmodifiedon` | DateTime | Last comment modification timestamp |
| `msp_customerneed` | Memo | Customer need description |
| `msp_competethreatlevel` | OptionSet | Compete threat level |
| `description` | Memo | Opportunity description |

### Comment JSON Structure

The `msp_forecastcommentsjsonfield` is a JSON string containing an array of comment objects:

```json
[
  {
    "userId": "{FE0C3504-3700-E911-A849-000D3A10B7CC}",
    "modifiedOn": "5/20/2025, 3:07:06 PM",
    "comment": "The actual comment text here"
  },
  {
    "userId": "{ANOTHER-GUID}",
    "modifiedOn": "5/21/2025, 10:15:00 AM",
    "comment": "Another comment from a different user"
  }
]
```

- **userId**: GUID of the Dynamics 365 system user who wrote the comment
- **modifiedOn**: Timestamp in US locale format (`M/D/YYYY, h:mm:ss AM/PM`)
- **comment**: The actual comment text (can contain newlines)

The plain text field `msp_forecastcomments` appears to be auto-derived from the JSON field by the MSX system (shows latest comment as plain text). **TBD:** Does PATCHing only the JSON field auto-update the plain text? The POC script was written but not executed (user stopped write tests on prod).

### Related Entities Checked

| Entity | Result |
|--------|--------|
| `annotations` on opportunity | Found 0 — not used for comments |
| `posts` on opportunity | Found 0 — not used for comments |
| `msp_opportunitycomments` | 404 — entity doesn't exist |
| `msp_comments` | 404 — entity doesn't exist |
| `msp_opportunitynotes` | 404 — entity doesn't exist |

**Conclusion:** All comments live in `msp_forecastcommentsjsonfield` on the opportunity entity itself.

### Metadata: Comment-Related String/Memo Attributes

From the EntityDefinitions query on `opportunity`:

**String attributes matching comment/note/forecast:**
- `msp_forecastcommentsjsonfield`: maxlen=1048576, label='Forecast Comments Json Field'
- `msp_forecastnotes`: maxlen=4000, label='Forecast Notes'

**All Memo (multiline) attributes:**
- `msp_forecastcomments`: maxlen=100000, label='Forecast Comments'
- `description`: maxlen=2000, label='Description'
- `msp_customerneed`: maxlen=2000, label='Customer Need'
- `msp_nextaction`: maxlen=2000, label='Next Action'

### Current Data Available During Milestone Sync

The `get_milestones_by_account()` API call already returns per milestone:
- `_msp_opportunityid_value` — opportunity GUID (currently NOT passed to sync)
- `_msp_opportunityid_value@OData.Community.Display.V1.FormattedValue` — opportunity name (already stored as `opportunity_name`)

This means **milestone sync already has opportunity GUIDs for free** — we just need to capture them.

---

## Implementation Plan

### Phase 1: Store Opportunity GUIDs During Milestone Sync

**Goal:** Capture opportunity GUIDs that we already receive from the milestone API, with zero additional API calls.

**Changes:**

1. **Milestone model** — Add `opportunity_id` column (String, the MSX GUID):
   ```python
   opportunity_id = db.Column(db.String(50), nullable=True)  # MSX opportunity GUID
   ```

2. **msx_api.py** `get_milestones_by_account()` — Include `_msp_opportunityid_value` in the returned dict:
   ```python
   milestones.append({
       ...
       "opportunity_id": raw.get("_msp_opportunityid_value"),  # NEW
       "opportunity_name": opp_name,
       ...
   })
   ```

3. **milestone_sync.py** — Store `opportunity_id` during create/update:
   ```python
   milestone.opportunity_id = msx_data.get("opportunity_id") or milestone.opportunity_id
   ```

4. **Migration** — Add `opportunity_id` column to milestones table.

**Result:** After next sync, every milestone has a link to its parent opportunity GUID. 

### Phase 2: Customer Opportunity List

**Goal:** On the customer view page, show a list of opportunities grouped from the customer's milestones.

**Approach:** No new API call needed. We derive the unique opportunities from the customer's milestones (which already have `opportunity_id` and `opportunity_name`).

**Changes:**

1. **Customer view template** — Add "Opportunities" section showing unique opportunities derived from milestones:
   - Group milestones by `opportunity_id`
   - Show: opportunity name, count of milestones, aggregate BACV
   - Each opportunity links to the opportunity detail page

2. **Route** — Add `opportunity_view` route that takes an opportunity GUID.

### Phase 3: Opportunity Detail Page (Fresh from MSX)

**Goal:** Show a single opportunity's details, fetched fresh from MSX on every page load. Includes milestones (from local DB) and comments (from MSX).

**New API function** in `msx_api.py`:

```python
def get_opportunity(opportunity_id: str) -> Dict[str, Any]:
    """Fetch a single opportunity from MSX by GUID.
    
    Returns: Dict with name, number, status, estimated_value, close_date,
             customer_need, description, comments (parsed JSON), etc.
    """
    url = (
        f"{CRM_BASE_URL}/opportunities({opportunity_id})"
        f"?$select=name,msp_opportunitynumber,statecode,statuscode,"
        f"estimatedvalue,estimatedclosedate,msp_customerneed,description,"
        f"msp_forecastcomments,msp_forecastcommentsjsonfield,"
        f"msp_forecastcomments_lastmodifiedon,msp_competethreatlevel,"
        f"_parentaccountid_value,_ownerid_value"
    )
    response = _msx_request('GET', url)
    # ... parse and return
```

**Template** (`opportunity_view.html`):
- Header: Opportunity name + number + status badge
- Info card: Estimated value, close date, owner, customer need
- Milestones section: Local milestones linked to this opportunity (from DB)
- Comments section: Rendered from `msp_forecastcommentsjsonfield`
- "Add Comment" form at the bottom

### Phase 4: Write Comments

**Goal:** Allow adding a comment to an opportunity's forecast comments from NoteHelper.

**Approach:**
1. Read current `msp_forecastcommentsjsonfield` (GET)
2. Append new comment object to the JSON array
3. PATCH the updated JSON back to the opportunity

```python
def add_opportunity_comment(opportunity_id: str, comment_text: str) -> Dict[str, Any]:
    """Append a comment to an opportunity's forecast comments field."""
    # 1. GET current comments
    url = f"{CRM_BASE_URL}/opportunities({opportunity_id})?$select=msp_forecastcommentsjsonfield"
    response = _msx_request('GET', url)
    current_json = json.loads(response.json().get('msp_forecastcommentsjsonfield') or '[]')
    
    # 2. Append new comment
    new_comment = {
        "userId": "{current_user_guid}",  # From WhoAmI or cached
        "modifiedOn": datetime.utcnow().strftime("%m/%d/%Y, %I:%M:%S %p"),
        "comment": comment_text
    }
    current_json.append(new_comment)
    
    # 3. PATCH back
    patch_url = f"{CRM_BASE_URL}/opportunities({opportunity_id})"
    payload = {"msp_forecastcommentsjsonfield": json.dumps(current_json)}
    response = _msx_request('PATCH', patch_url, json=payload)
    return {"success": response.status_code < 400}
```

**Open questions for Phase 4:**
- Does PATCHing `msp_forecastcommentsjsonfield` auto-update `msp_forecastcomments` (plain text)? Need to test.
- If not, should we PATCH both fields?
- What `userId` format does MSX expect? Need to verify with WhoAmI GUID.
- Character limit: 1,048,576 chars for JSON field (effectively unlimited for our use case).

### Phase 5 (Optional): Opportunity List Page

A standalone page showing all opportunities across all customers, with filters:
- Status (Open/Won/Lost)
- Customer
- Has milestones? 
- BACV range

This is lower priority since the customer view already shows per-customer opportunities.

---

## Architecture Decisions

### Why No Local Opportunity Model (for now)?

The user specified "opportunity scraped fresh every time we load the page." We honor this by:
- **Milestone sync** captures opportunity GUID + name (free data, already in the API response)
- **Opportunity detail page** always fetches fresh from MSX
- **Comments** are always read/written directly to MSX

If performance becomes an issue (many users, slow MSX), we can add a cache layer later.

### Why Store `opportunity_id` on Milestones?

We need the GUID to:
1. Link from customer view → opportunity detail page
2. Group milestones by opportunity
3. Fetch the opportunity from MSX via GUID

The milestone API already returns this field — just not currently captured.

### Comment Conflict Resolution

Since comments are appended to a JSON array, concurrent writes from different users (e.g., someone in MSX UI and someone in NoteHelper) could theoretically cause a lost update. Mitigation:
- Read → append → write is the same pattern MSX UI uses
- The window for conflict is very small (user writes comment, we read+write in <1 second)
- If this becomes an issue, we could add optimistic concurrency via `msp_forecastcomments_lastmodifiedon`

---

## MSX API Calls Summary

| Action | Method | Endpoint | New? |
|--------|--------|----------|------|
| Get milestones (with opp GUID) | GET | `/msp_engagementmilestones?$filter=...` | Modified (add field) |
| Get opportunity details | GET | `/opportunities({guid})?$select=...` | **New** |
| Read comments | GET | `/opportunities({guid})?$select=msp_forecastcommentsjsonfield` | **New** |
| Write comment | PATCH | `/opportunities({guid})` | **New** |
| Build opportunity URL | — | `https://microsoftsales.crm.dynamics.com/main.aspx?appid=...&pagetype=entityrecord&etn=opportunity&id={guid}` | **New** |

---

## Files to Change

| File | Changes |
|------|---------|
| `app/models.py` | Add `opportunity_id` to Milestone model |
| `app/migrations.py` | Add migration for new column |
| `app/services/msx_api.py` | Add `opportunity_id` to milestone dict; add `get_opportunity()`, `add_opportunity_comment()` |
| `app/services/milestone_sync.py` | Store `opportunity_id` during sync |
| `app/routes/msx.py` or new `app/routes/opportunities.py` | Add opportunity_view route |
| `templates/customer_view.html` | Add opportunities section |
| `templates/opportunity_view.html` | New template |
| `tests/` | Tests for new API functions, routes, model changes |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| PATCH comment field fails (permissions) | Low | High | Test with POC first (in a safe env, not prod) |
| MSX rate limiting on frequent opportunity reads | Low | Medium | One read per page load is very low volume |
| Comment JSON format changes | Very Low | Medium | Parse defensively, handle unknown fields |
| `msp_forecastcomments` (plain text) not auto-updating | Medium | Low | PATCH both fields if needed |

---

## Implementation Order

1. **Phase 1** first — it's zero risk (just storing a GUID we already receive)
2. **Phase 2** next — customer view grouping, no new API calls
3. **Phase 3** — opportunity detail page with fresh MSX fetch
4. **Phase 4** — write comments (needs POC validation first)

Each phase is independently shippable and testable.

---

*Created: 2025-01-17*  
*Branch: `feature/opportunity-comments`*
