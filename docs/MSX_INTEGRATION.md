# MSX (Microsoft Sales Experience) API Integration Guide

This document explains how we integrate with the MSX CRM (Dynamics 365) API for importing accounts, creating tasks, and managing milestones. Built from hard-won knowledge after much trial and error.

## Table of Contents

1. [Authentication](#authentication)
2. [Import Flow: Discovering Your Accounts](#import-flow-discovering-your-accounts)
3. [Fetching Account Team Members (Sellers & SEs)](#fetching-account-team-members-sellers--ses)
4. [Milestones](#milestones)
5. [Creating Tasks](#creating-tasks)
6. [HoK (Hands-on-Keyboard) Task Categories](#hok-hands-on-keyboard-task-categories)
7. [Important Gotchas](#important-gotchas)

---

## Authentication

### Overview

MSX uses Azure AD authentication. The easiest approach for a local/single-user app is to leverage the Azure CLI's cached token. This avoids dealing with client secrets, redirect URIs, or app registrations.

### Prerequisites

1. Azure CLI installed (`az --version`)
2. VPN connected (MSX CRM is internal to Microsoft)
3. User logged into the Microsoft corporate tenant

### Login Flow

```bash
# User runs this in terminal (must be on VPN)
az login --tenant 72f988bf-86f1-41af-91ab-2d7cd011db47
```

This opens a browser for interactive login. The token is cached locally by Azure CLI.

### Getting the Token Programmatically

Your server calls the Azure CLI to get a fresh token:

```python
import subprocess
import json

CRM_RESOURCE = "https://microsoftsales.crm.dynamics.com"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"

def get_msx_token():
    """Get token via az CLI."""
    cmd = f'az account get-access-token --resource "{CRM_RESOURCE}" --tenant "{TENANT_ID}" --output json'
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"az CLI failed: {result.stderr}")
    
    token_data = json.loads(result.stdout)
    return token_data["accessToken"]
```

**Why this approach?**
- No app registration needed
- No client secrets to manage
- Works with Microsoft's strict conditional access policies (which often block device code flow)
- User's permissions automatically apply

### Using the Token

All API calls include the token as a Bearer token:

```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=\"*\"",
}
```

**Important:** The `Prefer: odata.include-annotations="*"` header is crucial - it returns formatted values for lookups and option sets, which you'll need for human-readable labels.

### Base URL

```
https://microsoftsales.crm.dynamics.com/api/data/v9.2
```

---

## Import Flow: Discovering Your Accounts

### Goal

Find all accounts where the current user is assigned as a seller or solution engineer.

### Step 1: Get Current User ID

First, call `WhoAmI` to get the current user's system user ID:

```
GET /api/data/v9.2/WhoAmI
```

**Response:**
```json
{
    "UserId": "8c05af24-749d-e811-a848-000d3a1bbc2c",
    "BusinessUnitId": "...",
    "OrganizationId": "..."
}
```

### Step 2: Query Account Team Assignments

Query `msp_accountteams` to find all accounts where this user is assigned:

```
GET /api/data/v9.2/msp_accountteams
    ?$filter=_msp_systemuserid_value eq {user_id}
    &$select=_msp_accountid_value,msp_qualifier2
    &$top=500
```

**Why `msp_accountteams`?**

This entity maps users to accounts with their role (`msp_qualifier2`). A user can be assigned to the same account multiple times with different roles (e.g., both as a seller and an SE during a transition).

**Key Fields:**
| Field | Description |
|-------|-------------|
| `_msp_accountid_value` | The account GUID this assignment is for |
| `_msp_systemuserid_value` | The user GUID |
| `msp_qualifier2` | The role: "Cloud & AI", "Cloud & AI-Acq", "Cloud & AI Data", etc. |
| `msp_qualifier1` | Organization level: "Corporate", "Area", etc. |
| `msp_standardtitle` | Job title like "Specialists IC" |
| `msp_fullname` | User's display name |

**Relevant `msp_qualifier2` Values:**
| Value | Role |
|-------|------|
| `Cloud & AI` | Growth Seller (DSS) |
| `Cloud & AI-Acq` | Acquisition Seller |
| `Cloud & AI Data` | Data Solution Engineer |
| `Cloud & AI Infrastructure` | Infrastructure SE |
| `Cloud & AI Apps` | Apps SE |

Filter for these qualifier2 values and extract unique `_msp_accountid_value` values - that's your account list.

### Step 3: Batch Query Account Details

Now query the accounts themselves to get names and territory assignments:

```
GET /api/data/v9.2/accounts
    ?$filter=(accountid eq guid1 or accountid eq guid2 or ...)
    &$select=accountid,name,msp_mstopparentid,_territoryid_value
    &$top=100
```

**Key Fields:**
| Field | Description |
|-------|-------------|
| `accountid` | Account GUID |
| `name` | Account/company name |
| `msp_mstopparentid` | TPID (Top Parent ID) - unique customer identifier |
| `_territoryid_value` | Territory GUID (lookup field) |

### Step 4: Batch Query Territories

Get territory details using the territory IDs from the accounts:

```
GET /api/data/v9.2/territories
    ?$filter=(territoryid eq guid1 or territoryid eq guid2 or ...)
    &$select=territoryid,name,msp_accountteamunitname
    &$top=100
```

**Territory Naming Convention:**

Territory names follow a pattern: `{Region}.{Segment}.{SubArea}.{Code}`

Example: `East.SMECC.MAA.0601`
- Region: East
- Segment: SMECC (SMB, Enterprise, Corporate, Commercial)
- SubArea: MAA (Mid-Atlantic Area)
- Code: 0601 (POD 06, territory 01)

You can derive the POD name from the territory code:
```python
# "East.SMECC.MAA.0601" -> "East POD 06"
parts = territory_name.split(".")
region = parts[0]
pod_num = parts[-1][:2]
pod_name = f"{region} POD {pod_num}"
```

---

## Fetching Account Team Members (Sellers & SEs)

### The Problem: Record Limits and Pagination

Each account can have 250-300+ team members across all roles (area managers, CSU, CSA, sales, etc.). MSX returns max 100 records per query and **does not support `$skip`** for pagination.

**Pagination via `$skip` DOES NOT WORK in MSX:**
```
GET /msp_accountteams?$filter=...&$top=100&$skip=100  # ❌ Returns empty or errors
```

MSX uses a proprietary paging system via `@odata.nextLink` cookies, but the `msp_accountteams` entity doesn't return paging cookies consistently.

### The Solution: Server-Side Filtering

Filter server-side to reduce 300+ records per account to ~20-30:

```
GET /api/data/v9.2/msp_accountteams
    ?$filter=_msp_accountid_value eq {account_id}
            and msp_qualifier1 eq 'Corporate'
            and startswith(msp_qualifier2,'Cloud ')
    &$select=msp_fullname,msp_qualifier2,msp_standardtitle,_msp_systemuserid_value
    &$top=100
```

**Why this filter?**
- `msp_qualifier1 eq 'Corporate'` - Only corporate-level assignments (not Area or higher)
- `startswith(msp_qualifier2,'Cloud ')` - All Cloud & AI roles (sellers AND SEs)

This reduces 300+ records to ~20-30 per account, well under the 100 limit.

### Batching Multiple Accounts

You can query multiple accounts in one request:

```
GET /api/data/v9.2/msp_accountteams
    ?$filter=(_msp_accountid_value eq guid1 or _msp_accountid_value eq guid2 or _msp_accountid_value eq guid3)
            and msp_qualifier1 eq 'Corporate'
            and startswith(msp_qualifier2,'Cloud ')
    &$select=_msp_accountid_value,msp_fullname,msp_qualifier2,msp_standardtitle,_msp_systemuserid_value
    &$top=100
```

**Batch Size Calculation:**

With ~22 records per account after filtering, you can safely batch:
- 3 accounts: 3 × 22 = 66 records (safe)
- 4 accounts: 4 × 22 = 88 records (borderline)
- 5 accounts: 5 × 22 = 110 records (exceeds limit!)

Use **batch size of 3** to stay safely under 100.

### Identifying Sellers vs SEs

**Sellers:** Look for `msp_qualifier2` = "Cloud & AI" or "Cloud & AI-Acq" AND `msp_standardtitle` contains "Specialists IC"

The title filter is important! Without it, you'll also get:
- CSU (Customer Success Unit)
- CSA (Cloud Solution Architects)
- Managers
- Other roles

```python
if qualifier2 in ("Cloud & AI", "Cloud & AI-Acq") and "Specialists IC" in standardtitle:
    # This is a seller
    seller_type = "Growth" if qualifier2 == "Cloud & AI" else "Acquisition"
```

**SEs:** Simply check `msp_qualifier2`:
```python
se_map = {
    "Cloud & AI Data": "data_se",
    "Cloud & AI Infrastructure": "infra_se",
    "Cloud & AI Apps": "apps_se"
}
```

---

## Milestones

### What Are Milestones?

Milestones (`msp_engagementmilestone`) are consumption plays - tracked customer engagements designed to drive Azure usage. They're linked to accounts and can have tasks created against them.

### Querying Milestones for an Account

```
GET /api/data/v9.2/msp_engagementmilestones
    ?$filter=_msp_parentaccount_value eq '{account_id}'
    &$select=msp_engagementmilestoneid,msp_name,msp_milestonestatus,
             msp_milestonenumber,_msp_opportunityid_value,msp_monthlyuse,
             _msp_workloadlkid_value
    &$orderby=msp_name
```

**Key Fields:**
| Field | Description |
|-------|-------------|
| `msp_engagementmilestoneid` | Milestone GUID |
| `msp_name` | Milestone title/description |
| `msp_milestonenumber` | Internal milestone number |
| `msp_milestonestatus` | Status code (numeric) |
| `msp_milestonestatus@OData.Community.Display.V1.FormattedValue` | Status label ("On Track", "At Risk", etc.) |
| `_msp_opportunityid_value` | Linked opportunity GUID |
| `_msp_opportunityid_value@OData.Community.Display.V1.FormattedValue` | Opportunity name |
| `_msp_workloadlkid_value@OData.Community.Display.V1.FormattedValue` | Workload name |
| `msp_monthlyuse` | Monthly usage amount |

**Milestone Status Values:**
- On Track
- At Risk
- Blocked
- Completed
- Cancelled
- Lost to Competitor
- Hygiene/Duplicate

### Building Milestone URLs

To link directly to a milestone in MSX:

```python
MSX_APP_ID = "fe0c3504-3700-e911-a849-000d3a10b7cc"

def build_milestone_url(milestone_id):
    return (
        f"https://microsoftsales.crm.dynamics.com/main.aspx"
        f"?appid={MSX_APP_ID}"
        f"&pagetype=entityrecord"
        f"&etn=msp_engagementmilestone"
        f"&id={milestone_id}"
    )
```

---

## Creating Tasks

### Overview

Tasks are linked to milestones and credit the user for customer engagement. The task category determines whether it counts for HoK credit.

### Creating a Task

```
POST /api/data/v9.2/tasks
Content-Type: application/json

{
    "subject": "Technical architecture review call",
    "msp_taskcategory": 861980004,
    "scheduleddurationminutes": 60,
    "prioritycode": 1,
    "regardingobjectid_msp_engagementmilestone@odata.bind": "/msp_engagementmilestones({milestone_id})",
    "ownerid@odata.bind": "/systemusers({user_id})"
}
```

**Key Fields:**
| Field | Description |
|-------|-------------|
| `subject` | Task title |
| `msp_taskcategory` | Category code (see HoK section below) |
| `scheduleddurationminutes` | Duration in minutes |
| `prioritycode` | 0=Low, 1=Normal, 2=High |
| `regardingobjectid_msp_engagementmilestone@odata.bind` | Links to milestone |
| `ownerid@odata.bind` | Task owner (the SE/seller) |
| `description` | Optional description text |

### Getting the Task ID

The created task ID is returned in the `OData-EntityId` response header:

```
OData-EntityId: https://microsoftsales.crm.dynamics.com/api/data/v9.2/tasks(12345678-1234-1234-1234-123456789abc)
```

Parse the GUID using regex:
```python
match = re.search(r'tasks\(([a-f0-9-]{36})\)', entity_id_header, re.IGNORECASE)
task_id = match.group(1) if match else None
```

---

## HoK (Hands-on-Keyboard) Task Categories

HoK tasks count toward engagement metrics and credit. These are the **only categories that count for HoK**:

| Category | Code | Description |
|----------|------|-------------|
| Architecture Design Session | 861980004 | Deep technical design sessions |
| Blocker Escalation | 861980006 | Escalating technical blockers |
| Briefing | 861980008 | Executive/technical briefings |
| Consumption Plan | 861980007 | Planning Azure consumption |
| Demo | 861980002 | Product/solution demos |
| PoC/Pilot | 861980005 | Proof of concept work |
| Technical Close/Win Plan | 606820005 | Technical win planning |
| Workshop | 861980001 | Hands-on workshops |

### Non-HoK Categories (For Reference)

These exist but don't count for HoK:

| Category | Code |
|----------|------|
| ACE | 606820000 |
| Call Back Requested | 861980010 |
| Cross Segment | 606820001 |
| Cross Workload | 606820002 |
| Customer Engagement | 861980000 |
| External (Co-creation of Value) | 861980013 |
| Internal | 861980012 |
| Negotiate Pricing | 861980003 |
| New Partner Request | 861980011 |
| Post Sales | 606820003 |
| RFP/RFI | 861980009 |
| Tech Support | 606820004 |

---

## Important Gotchas

### 1. No `$skip` Pagination

MSX does not support standard OData `$skip`. If you need more than 100 records, you must either:
- Use server-side filtering to reduce the result set
- Use `@odata.nextLink` (but it's inconsistent across entities)

### 2. VPN Required

All MSX API calls require VPN connection to Microsoft corpnet. Token acquisition also requires VPN.

### 3. Token Expiry

Azure CLI tokens expire after ~1 hour. Cache the token and refresh when needed:
```python
if token_expiry < utc_now() + timedelta(minutes=5):
    refresh_token()
```

### 4. Lookup Field Formatting

Lookup fields (foreign keys) come with two values:
- `_fieldname_value` - The raw GUID
- `_fieldname_value@OData.Community.Display.V1.FormattedValue` - Display name

You need the `Prefer: odata.include-annotations="*"` header to get the formatted values.

### 5. Filter Gotchas

- GUIDs in filters don't need quotes: `_msp_accountid_value eq abc123-def456-...`
- String values need single quotes: `msp_qualifier1 eq 'Corporate'`
- Use `startswith()` for prefix matching: `startswith(msp_qualifier2,'Cloud ')`
- Multiple OR conditions need parentheses: `(a eq 1 or a eq 2) and b eq 3`

### 6. 401/403 on First Request After Token Refresh

Sometimes the first request after a token refresh fails with 401/403 even though the token is valid. Implement automatic retry:

```python
response = make_request(url, headers)
if response.status_code in (401, 403):
    refresh_token()
    new_headers = build_headers(get_fresh_token())
    response = make_request(url, new_headers)  # Retry once
```

### 7. Entity Names Are Plural

Most entity names are plural in the API:
- `accounts` (not account)
- `territories` (not territory)
- `msp_engagementmilestones` (not msp_engagementmilestone)
- `tasks` (not task)
- `systemusers` (not systemuser)

### 8. App ID for URLs

When building URLs to open records in MSX, include the app ID:
```
?appid=fe0c3504-3700-e911-a849-000d3a10b7cc
```

Without it, MSX might not load the correct app context.

---

## Summary of Key API Calls

### Authentication & User Info
```
GET /WhoAmI
GET /systemusers({user_id})
```

### Discovering Accounts
```
GET /msp_accountteams?$filter=_msp_systemuserid_value eq {user_id}
GET /accounts?$filter=(accountid eq guid1 or accountid eq guid2 or ...)
GET /territories?$filter=(territoryid eq guid1 or ...)
```

### Getting Account Team (Sellers/SEs)
```
GET /msp_accountteams
    ?$filter=(_msp_accountid_value eq guid1 or ...)
             and msp_qualifier1 eq 'Corporate'
             and startswith(msp_qualifier2,'Cloud ')
```

### Milestones
```
GET /msp_engagementmilestones?$filter=_msp_parentaccount_value eq '{account_id}'
```

### Tasks
```
POST /tasks (with JSON body)
```

---

## Questions?

This was built through trial and error integrating with MSX. If something doesn't work or you find better approaches, please update this doc!
