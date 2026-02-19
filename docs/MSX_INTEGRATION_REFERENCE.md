# MSX (Dynamics 365) Integration Reference for NoteHelper

> This document catalogs every read/write operation that MSX Helper performs against the Dynamics 365 Web API, along with the authentication mechanism that makes it possible. The goal is to identify which operations could replace the manual copy-paste workflows in NoteHelper (looking up account URLs by TPID, pasting milestone URLs, etc.).

---

## Table of Contents

- [Authentication — How MSX Helper Gets a Token](#authentication--how-msx-helper-gets-a-token)
  - [What NoteHelper Should Use — Device Code Flow with MSAL](#what-notehelper-should-use--device-code-flow-with-msal)
- [How Requests Are Made](#how-requests-are-made)
- [What NoteHelper Has Today vs. What Could Be Automated](#what-notehelper-has-today-vs-what-could-be-automated)
- [Complete API Catalog by Entity](#complete-api-catalog-by-entity)
  - [WhoAmI — Connectivity Check](#1-whoami--connectivity-check)
  - [Accounts — Lookup by TPID or Name](#2-accounts--lookup-by-tpid-or-name)
  - [Opportunities — Search, List, Update](#3-opportunities--search-list-update)
  - [Milestones (msp_engagementmilestones)](#4-milestones-msp_engagementmilestones)
  - [Deal Team / Access Team Membership](#5-deal-team--access-team-membership)
  - [Tasks — Create and List](#6-tasks--create-and-list)
  - [Users — Lookup for Teams Chat](#7-users--lookup-for-teams-chat)
  - [Batch Requests](#8-batch-requests)
- [Required Headers](#required-headers)
- [Key Constants](#key-constants)
- [Adapting This for NoteHelper (Python/Flask)](#adapting-this-for-notehelper-pythonflask)

---

## Authentication — How MSX Helper Gets a Token

MSX Helper authenticates using **Azure CLI** (`az account get-access-token`). There is no app registration, no client secret, and no OAuth redirect flow — it piggybacks on your existing `az login` session.

### The Command

```bash
az account get-access-token \
  --resource https://microsoftsales.crm.dynamics.com \
  --tenant 72f988bf-86f1-41af-91ab-2d7cd011db47 \
  --query accessToken \
  -o tsv
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| `--resource` | `https://microsoftsales.crm.dynamics.com` | The CRM instance. This is the `aud` (audience) claim in the JWT. |
| `--tenant` | `72f988bf-86f1-41af-91ab-2d7cd011db47` | Microsoft's corporate tenant ID. |
| `--query accessToken` | — | JMESPath to extract just the token string. |
| `-o tsv` | — | Raw text output (no JSON wrapping). |

### What You Get Back

A **JWT Bearer token** (typically valid for ~60-75 minutes). The token is decoded client-side (no crypto verification) to extract:

- `name` / `upn` — authenticated user display name and UPN
- `exp` — expiry timestamp (used for countdown/auto-refresh)
- `aud` — must match the CRM URL

### Auto-Refresh

MSX Helper polls every 60 seconds. If the token has < 10 minutes remaining, it re-runs the `az` command to get a fresh one. This is invisible to the user.

### What NoteHelper Should Use — Device Code Flow with MSAL

Since NoteHelper is a **Python/Flask web app** (not an Electron desktop app), the `az` CLI approach doesn't hold up well — the `az login` session can expire, the CLI may not be installed on the host, and a redeploy wipes the auth state.

**The recommended approach is the OAuth 2.0 Device Code Flow via MSAL for Python.** This gives you:

- A **one-time browser login** triggered from the admin panel (no redirect URI needed)
- A **refresh token** that the backend caches and uses to silently renew access tokens for months
- A **manual "re-authenticate" button** in the admin panel for when things go wrong (redeploy, host restart, expired refresh token)

#### How the Device Code Flow Works

1. **Admin clicks "Authenticate with MSX"** in the NoteHelper admin panel
2. The backend calls MSAL's `initiate_device_flow()` — this contacts Azure AD and returns:
   - A `user_code` (e.g., `ABCD1234`)
   - A `verification_uri` (e.g., `https://microsoft.com/devicelogin`)
   - A `device_code` (opaque string used by the backend to poll for completion)
3. The admin panel displays the code and a clickable link to `https://microsoft.com/devicelogin`
4. The user opens the link, enters the code, and signs in with their Microsoft account
5. Meanwhile, the backend **polls** Azure AD using `acquire_token_by_device_flow()` — this blocks until the user completes login or the flow times out (~15 minutes)
6. On success, MSAL returns an **access token** + **refresh token**
7. The backend caches these (MSAL's `SerializableTokenCache`) and persists the cache to disk or database
8. For all subsequent CRM calls, the backend calls `acquire_token_silent()` — MSAL automatically uses the refresh token to get new access tokens as they expire

#### Prerequisites — Azure AD App Registration

You need a **public client** app registration in Azure AD (no client secret required for device code flow):

1. Go to [Azure Portal > App Registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. **New registration**:
   - Name: `NoteHelper CRM` (or whatever you want)
   - Supported account types: **Single tenant** (Microsoft corporate tenant only)
   - Redirect URI: **leave blank** (device code flow doesn't use one)
3. Note the **Application (client) ID** — you'll need this
4. Under **Authentication**:
   - Enable **"Allow public client flows"** → Yes (required for device code)
5. Under **API Permissions**:
   - Add permission → **Dynamics CRM** → Delegated → `user_impersonation`
   - (This is the only permission needed — it lets the app act as the signed-in user against CRM)
6. The **Tenant ID** is `72f988bf-86f1-41af-91ab-2d7cd011db47` (Microsoft corporate)

#### MSAL Python Implementation

```python
# pip install msal

import msal
import json
import os

# App registration values
CLIENT_ID = "your-app-client-id-here"  # From Azure AD app registration
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://microsoftsales.crm.dynamics.com/.default"]

# Token cache persistence path (or store in database)
TOKEN_CACHE_FILE = "data/msx_token_cache.json"


def _load_cache():
    """Load MSAL token cache from disk."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(cache):
    """Persist MSAL token cache to disk."""
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


def _get_msal_app(cache=None):
    """Create an MSAL public client application."""
    return msal.PublicClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        token_cache=cache
    )


def start_device_code_flow():
    """
    Initiate device code flow. Returns the flow object containing:
    - user_code: code to display to the user
    - verification_uri: URL for the user to visit
    - message: human-readable instruction string
    - (internal fields used by acquire_token_by_device_flow)
    
    Call this from the admin panel endpoint.
    """
    cache = _load_cache()
    app = _get_msal_app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow initiation failed: {flow.get('error_description', 'Unknown error')}")
    return flow


def complete_device_code_flow(flow):
    """
    Poll Azure AD until the user completes login.
    This BLOCKS for up to ~15 minutes (until user completes or flow expires).
    Run this in a background thread.
    
    Returns the token result dict on success, or raises on failure.
    """
    cache = _load_cache()
    app = _get_msal_app(cache)
    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)
    
    if "access_token" in result:
        return result
    else:
        raise RuntimeError(result.get("error_description", "Authentication failed"))


def get_crm_token():
    """
    Get a valid CRM access token. Uses cached/refresh tokens silently.
    If no cached token exists or refresh fails, raises an error
    (admin needs to re-authenticate via device code flow).
    """
    cache = _load_cache()
    app = _get_msal_app(cache)
    
    # Find cached accounts
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("No cached MSX credentials. Admin must authenticate via Settings.")
    
    # Try silent acquisition (uses refresh token automatically)
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(cache)
    
    if result and "access_token" in result:
        return result["access_token"]
    
    raise RuntimeError("Token refresh failed. Admin must re-authenticate via Settings.")


def clear_crm_auth():
    """Clear all cached tokens. Used when admin wants to force re-auth."""
    if os.path.exists(TOKEN_CACHE_FILE):
        os.remove(TOKEN_CACHE_FILE)
```

#### Admin Panel UX Flow

The admin panel should have an **MSX Authentication** section with:

1. **Status indicator** — show whether MSX auth is active:
   - Call `get_crm_token()` in a try/except → if it returns a token, decode the JWT to show the authenticated user name and token expiry
   - If it raises, show "Not authenticated" with the button below
2. **"Authenticate with MSX" button** — kicks off the device code flow:
   - Backend calls `start_device_code_flow()` and returns the `user_code` + `verification_uri`
   - Frontend shows: "Go to **https://microsoft.com/devicelogin** and enter code **ABCD1234**" (with the link clickable)
   - Backend starts polling in a background thread via `complete_device_code_flow(flow)`
   - Once the user completes login, the page updates to show "Authenticated as {name}" 
   - The flow times out after ~15 minutes if not completed
3. **"Disconnect" button** — calls `clear_crm_auth()` to wipe the cached tokens

#### Token Lifecycle

| Event | What happens |
|-------|-------------|
| **First auth** | Admin clicks button → device code flow → access token (60-75 min) + refresh token (days-months) cached |
| **Normal API call** | `get_crm_token()` → `acquire_token_silent()` → MSAL checks if access token expired → if yes, uses refresh token to get new one automatically → returns valid access token |
| **Refresh token expires** (rare, months) | `acquire_token_silent()` fails → `get_crm_token()` raises → MSX features show "re-auth needed" message → admin clicks button again |
| **Redeploy / restart** | Token cache loaded from `TOKEN_CACHE_FILE` (persisted on disk or DB) → `acquire_token_silent()` picks up where it left off → no user action needed unless cache is lost |
| **Cache lost** (new host, disk wiped) | Same as refresh token expiry — admin re-authenticates via device code flow |

#### Background Auto-Refresh (Optional)

MSX Helper polls every 60 seconds to keep the token fresh. NoteHelper could do the same with a lightweight approach — call `get_crm_token()` on a schedule (e.g., APScheduler or a simple threading timer) to keep the cache warm:

```python
# Optional: background token refresh every 30 minutes
import threading

def _refresh_token_periodically():
    try:
        get_crm_token()  # This triggers silent refresh if needed
    except Exception:
        pass  # Will be caught on next actual API call
    threading.Timer(1800, _refresh_token_periodically).start()

# Call once at app startup
_refresh_token_periodically()
```

This isn't strictly required — `acquire_token_silent()` refreshes on demand — but it prevents the first CRM call after a long idle from having extra latency.

---

## How Requests Are Made

All CRM calls go to:

```
https://microsoftsales.crm.dynamics.com/api/data/v9.2/{entityPath}
```

Every request includes the Bearer token and OData headers (see [Required Headers](#required-headers)).

MSX Helper wraps every call with:
- **Retry with exponential backoff** — retries on 408, 429, 500, 502, 503, 504
- **Retry-After header support** — respects 429 throttling
- **Timeout** — 20s per request (30s max)
- **In-memory cache** — GET responses cached for 5 minutes (for stable data like accounts)
- **OData injection prevention** — single quotes escaped: `value.replace(/'/g, "''")`

---

## What NoteHelper Has Today vs. What Could Be Automated

| NoteHelper Workflow Today | Manual Steps | What MSX Helper's API Can Do |
|---------------------------|-------------|-------------------------------|
| **Link TPID to MSX account URL** — User manually goes to MSX, searches by TPID, copies account URL, pastes into `tpid_url` field | Open MSX → search → copy URL → paste | **Auto-resolve**: `GET accounts?$filter=msp_mstopparentid eq '{tpid}'` returns `accountid` → construct URL `https://microsoftsales.crm.dynamics.com/main.aspx?appid=...&pagetype=entityrecord&etn=account&id={accountid}` |
| **View opportunities for a customer** — User manually navigates MSX by account to find opportunities | Open MSX → navigate → browse | **API query**: `GET opportunities?$filter=_parentaccountid_value eq '{accountId}' and statecode eq 0` returns all open opportunities with name, value, close date |
| **Link milestone URLs to call logs** — User copies milestone URL from MSX browser, pastes into NoteHelper milestone record | Open MSX → find milestone → copy URL → paste | **API query**: `GET msp_engagementmilestones?$filter=_msp_opportunityid_value eq '{oppId}'` returns all milestones with IDs, names, statuses, dates — could auto-populate links or show milestones inline |
| **Check deal team membership** — No current workflow | N/A | **API query**: Check if user is on deal team; join/leave via `AddUserToRecordTeam` action |
| **Create tasks against milestones** — User does this manually in MSX | Open MSX → navigate → create task | **API write**: `POST tasks` with milestone binding — create tasks programmatically |

---

## Complete API Catalog by Entity

### 1. WhoAmI — Connectivity Check

```
GET /api/data/v9.2/WhoAmI
```

Returns `{ UserId, BusinessUnitId, OrganizationId }`. Used to verify the token works and CRM is reachable (VPN check). The `UserId` is the current user's `systemuserid` GUID, needed for team membership queries.

---

### 2. Accounts — Lookup by TPID or Name

#### Look up accounts by TPID

```
GET /api/data/v9.2/accounts
  ?$filter=msp_mstopparentid eq '{tpid}'
  &$select=accountid,name,msp_mstopparentid
```

**This is the query that can auto-resolve NoteHelper's `tpid_url` field.** Given a numeric TPID, it returns the account GUID which you can use to build a direct MSX link.

For multiple TPIDs in one call (used for bulk loading):
```
$filter=msp_mstopparentid eq '{tpid1}' or msp_mstopparentid eq '{tpid2}' or ...
```

Config: `{ cache: true, cacheTtlMs: 300000 }` (cached 5 minutes)

#### Look up accounts by name

```
GET /api/data/v9.2/accounts
  ?$filter=name eq '{accountName}'
  &$select=accountid,name
```

For multiple names: combine with `or`. Names must be OData-escaped (`'` → `''`).

---

### 3. Opportunities — Search, List, Update

#### List open opportunities for specific accounts

```
GET /api/data/v9.2/opportunities
  ?$filter=(_parentaccountid_value eq '{accountId1}' or ...) and statecode eq 0
  &$select=opportunityid,name,estimatedclosedate,msp_estcompletiondate,
           msp_consumptionconsumedrecurring,_ownerid_value,_parentaccountid_value
  &$orderby=name
  &$count=true
```

Uses pagination (`getAllPages`) — follows `@odata.nextLink` automatically.
Account IDs are chunked (max 25 per request) to stay under OData URL length limits.

#### Search by opportunity number

```
GET /api/data/v9.2/opportunities
  ?$filter=msp_opportunitynumber eq '{number}'
  &$select=opportunityid,name,estimatedclosedate,msp_estcompletiondate,
           msp_consumptionconsumedrecurring,_ownerid_value,_parentaccountid_value
```

#### Load single opportunity by GUID

```
GET /api/data/v9.2/opportunities({guid})
  ?$select=opportunityid,name,estimatedclosedate,msp_estcompletiondate,
           msp_consumptionconsumedrecurring,_ownerid_value,_parentaccountid_value,
           msp_opportunitynumber
```

#### Update an opportunity (PATCH)

```
PATCH /api/data/v9.2/opportunities({opportunityId})
Content-Type: application/json

{ ...field updates... }
```

Used for bulk updates — iterates over an array of `{ opportunityId, data }` objects.

---

### 4. Milestones (msp_engagementmilestones)

#### List milestones for an opportunity

```
GET /api/data/v9.2/msp_engagementmilestones
  ?$filter=_msp_opportunityid_value eq '{opportunityId}'
  &$orderby=msp_milestonedate
```

Returns all milestones with: `msp_engagementmilestoneid`, `msp_milestonenumber`, `msp_name`, `msp_milestonedate`, `msp_milestonestatus`, `msp_monthlyuse`, `msp_commitmentrecommendation`, `msp_milestonecategory`, `_ownerid_value`, `_msp_workloadlkid_value`, `_msp_opportunityid_value`.

**This can replace manual milestone URL pasting.** Instead of the user copying a URL, NoteHelper could query milestones by opportunity and let the user pick from a list.

#### Search by milestone number

```
GET /api/data/v9.2/msp_engagementmilestones
  ?$filter=msp_milestonenumber eq '{number}'
```

#### Load single milestone (for editing)

```
GET /api/data/v9.2/msp_engagementmilestones({milestoneId})
  ?$select=msp_engagementmilestoneid,msp_milestonenumber,msp_name,
           _msp_workloadlkid_value,msp_commitmentrecommendation,
           msp_milestonecategory,msp_monthlyuse,msp_milestonedate,
           msp_milestonestatus,_ownerid_value,_msp_opportunityid_value,
           msp_forecastcommentsjsonfield,msp_forecastcomments
```

#### Update a milestone (PATCH)

```
PATCH /api/data/v9.2/msp_engagementmilestones({milestoneId})
Content-Type: application/json

{
  "msp_milestonedate": "2026-03-15",
  "msp_monthlyuse": 1500.00,
  "msp_forecastcommentsjsonfield": "[{\"text\":\"...\",\"author\":\"...\",\"date\":\"...\"}]",
  "msp_forecastcomments": "Plain text summary of comments"
}
```

#### Load milestones owned by current user

```
GET /api/data/v9.2/msp_engagementmilestones
  ?$filter=_ownerid_value eq '{userId}'
```

Uses `getAllPages: true` for full pagination.

#### Load milestones where user is on the access team (FetchXML)

```
GET /api/data/v9.2/msp_engagementmilestones?fetchXml={urlEncoded}
```

```xml
<fetch version="1.0" output-format="xml-platform" mapping="logical"
       distinct="true" no-lock="true">
  <entity name="msp_engagementmilestone">
    <attribute name="msp_engagementmilestoneid"/>
    <attribute name="msp_milestonenumber"/>
    <attribute name="msp_name"/>
    <attribute name="msp_milestonedate"/>
    <attribute name="msp_milestonestatus"/>
    <attribute name="msp_monthlyuse"/>
    <attribute name="msp_commitmentrecommendation"/>
    <attribute name="msp_milestonecategory"/>
    <attribute name="ownerid"/>
    <attribute name="msp_workloadlkid"/>
    <attribute name="msp_opportunityid"/>
    <link-entity name="team" from="regardingobjectid"
                 to="msp_engagementmilestoneid" link-type="inner" alias="t">
      <filter type="and">
        <condition attribute="teamtype" operator="eq" value="1"/>
        <condition attribute="teamtemplateid" operator="eq"
                   value="{MILESTONE_TEAM_TEMPLATE_ID}"/>
      </filter>
      <link-entity name="teammembership" from="teamid" to="teamid"
                   link-type="inner" alias="tm">
        <filter type="and">
          <condition attribute="systemuserid" operator="eq"
                     value="{currentUserId}"/>
        </filter>
      </link-entity>
    </link-entity>
  </entity>
</fetch>
```

---

### 5. Deal Team / Access Team Membership

#### Check membership (primary method — via team association)

```
GET /api/data/v9.2/systemusers({userId})/teammembership_association
  ?$select=_regardingobjectid_value,teamid
  &$filter=teamtemplateid eq guid'{TEAM_TEMPLATE_ID}'
           and teamtype eq 1
           and (_regardingobjectid_value eq guid'{recordId1}' or ...)
```

Works for both opportunity and milestone teams — just use the appropriate `TEAM_TEMPLATE_ID`.

#### Check membership (fallback — msp_dealteams entity)

```
GET /api/data/v9.2/msp_dealteams
  ?$filter=_msp_dealteamuserid_value eq '{userId}'
           and (_msp_parentopportunityid_value eq '{oppId1}' or ...)
           and statecode eq 0
  &$select=_msp_parentopportunityid_value
```

#### Join a team

```
POST /api/data/v9.2/systemusers({userId})/Microsoft.Dynamics.CRM.AddUserToRecordTeam
Content-Type: application/json

{
  "Record": {
    "@odata.type": "Microsoft.Dynamics.CRM.opportunity",
    "opportunityid": "{recordId}"
  },
  "TeamTemplate": {
    "@odata.type": "Microsoft.Dynamics.CRM.teamtemplate",
    "teamtemplateid": "{TEAM_TEMPLATE_ID}"
  }
}
```

For milestones, replace `opportunity` with `msp_engagementmilestone` and `opportunityid` with `msp_engagementmilestoneid`.

#### Leave a team

```
POST /api/data/v9.2/systemusers({userId})/Microsoft.Dynamics.CRM.RemoveUserFromRecordTeam
```

Same body structure as join.

---

### 6. Tasks — Create and List

#### Create a task linked to a milestone

```
POST /api/data/v9.2/tasks
Content-Type: application/json

{
  "subject": "Task title",
  "msp_taskcategory": 865420001,
  "scheduleddurationminutes": 60,
  "prioritycode": 1,
  "regardingobjectid_msp_engagementmilestone@odata.bind":
    "/msp_engagementmilestones({milestoneId})",
  "ownerid@odata.bind": "/systemusers({userId})"
}
```

Task category values (enum):
- Used in a dropdown in the UI — specific numeric values from the CRM optionset.

#### List tasks for a milestone

```
GET /api/data/v9.2/tasks
  ?$filter=_regardingobjectid_value eq '{milestoneId}'
  &$select=subject,scheduledend,createdon,activityid,msp_taskcategory,
           scheduleddurationminutes,statecode,statuscode,_ownerid_value
  &$orderby=createdon desc
```

---

### 7. Users — Lookup for Teams Chat

```
GET /api/data/v9.2/systemusers({userId})
  ?$select=internalemailaddress
```

Returns the user's email, which is used to build a Teams deep link:
```
https://teams.microsoft.com/l/chat/0/0?users={email}
```

---

### 8. Batch Requests

```
POST /api/data/v9.2/$batch
Content-Type: multipart/mixed; boundary=batch_{batchId}

--batch_{batchId}
Content-Type: multipart/mixed; boundary=changeset_{changeSetId}

--changeset_{changeSetId}
Content-Type: application/http
Content-Transfer-Encoding: binary

POST /api/data/v9.2/systemusers({userId})/Microsoft.Dynamics.CRM.AddUserToRecordTeam HTTP/1.1
Content-Type: application/json

{...body...}

--changeset_{changeSetId}--
--batch_{batchId}--
```

Used for bulk join/leave team operations. Adaptive chunk sizing: starts at 15 operations per batch, adjusts between 5–25 based on measured latency.

---

## Required Headers

Every CRM API request must include:

```
Authorization: Bearer {accessToken}
OData-MaxVersion: 4.0
OData-Version: 4.0
Content-Type: application/json
Accept: application/json
Prefer: odata.include-annotations="*"
Cache-Control: no-cache
If-None-Match:
```

The `Prefer: odata.include-annotations="*"` header is important — it returns formatted values (e.g., optionset labels, lookup names) alongside raw values.

---

## Key Constants

| Constant | Value | Notes |
|----------|-------|-------|
| CRM Base URL | `https://microsoftsales.crm.dynamics.com` | Configurable per user in settings |
| API Version | `v9.2` | OData v4.0 compatible |
| Tenant ID | `72f988bf-86f1-41af-91ab-2d7cd011db47` | Microsoft corporate tenant |
| Opportunity Team Template ID | `cc923a9d-7651-e311-9405-00155db3ba1e` | For deal team operations |
| Milestone Team Template ID | `316e4735-9e83-eb11-a812-0022481e1be0` | For milestone access team operations |

---

## Adapting This for NoteHelper (Python/Flask)

### Recommended Starting Points

Given NoteHelper already has TPIDs for every customer, the highest-impact integrations would be:

#### 1. Auto-Resolve TPID → Account URL (eliminates manual lookup)

```python
import requests

def get_account_by_tpid(tpid, token):
    url = f"https://microsoftsales.crm.dynamics.com/api/data/v9.2/accounts"
    params = {
        "$filter": f"msp_mstopparentid eq '{tpid}'",
        "$select": "accountid,name"
    }
    headers = get_crm_headers(token)
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if data.get("value"):
        account = data["value"][0]
        account_id = account["accountid"]
        # Build the MSX direct link
        return f"https://microsoftsales.crm.dynamics.com/main.aspx?etn=account&id={account_id}&pagetype=entityrecord"
    return None
```

You could run this when a customer is created/edited and auto-fill the `tpid_url` field.

#### 2. List Opportunities for a Customer

```python
def get_opportunities_for_account(account_id, token):
    url = f"https://microsoftsales.crm.dynamics.com/api/data/v9.2/opportunities"
    params = {
        "$filter": f"_parentaccountid_value eq '{account_id}' and statecode eq 0",
        "$select": "opportunityid,name,estimatedvalue,estimatedclosedate",
        "$orderby": "name"
    }
    headers = get_crm_headers(token)
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json().get("value", [])
```

#### 3. List Milestones for an Opportunity

```python
def get_milestones_for_opportunity(opportunity_id, token):
    url = f"https://microsoftsales.crm.dynamics.com/api/data/v9.2/msp_engagementmilestones"
    params = {
        "$filter": f"_msp_opportunityid_value eq '{opportunity_id}'",
        "$orderby": "msp_milestonedate"
    }
    headers = get_crm_headers(token)
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json().get("value", [])
```

#### Helper: Standard CRM Headers

```python
def get_crm_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": 'odata.include-annotations="*"',
        "Cache-Control": "no-cache",
        "If-None-Match": ""
    }
```

#### Helper: Get Token via Azure CLI (Python)

```python
import subprocess

def get_crm_token():
    """Get CRM access token via Azure CLI. Requires `az login` session."""
    result = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://microsoftsales.crm.dynamics.com",
         "--tenant", "72f988bf-86f1-41af-91ab-2d7cd011db47",
         "--query", "accessToken",
         "-o", "tsv"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"Azure CLI auth failed: {result.stderr.strip()}")
    return result.stdout.strip()
```

### Input Sanitization

Always escape single quotes in OData string filters to prevent injection:

```python
def sanitize_odata_string(value):
    """Escape single quotes for OData filter values."""
    return value.replace("'", "''")
```

### OData Pagination

Dynamics 365 returns max 5,000 records per response. If there are more, the response includes `@odata.nextLink`. Follow it to get the next page:

```python
def get_all_pages(url, headers):
    """Fetch all pages of an OData response."""
    all_records = []
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        all_records.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return all_records
```
