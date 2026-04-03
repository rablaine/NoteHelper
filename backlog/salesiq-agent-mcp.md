# SalesIQ Agent & MCP Server

## Overview

Build an in-app AI chat panel ("SalesIQ") backed by Azure OpenAI via the existing APIM gateway, plus an MCP server so VS Code Copilot can interact with SalesBuddy data. Both consume a shared tool registry so logic is never duplicated.

## Implementation Phases

### Phase 1: Tool Registry & Scaffolding - DONE

**Status:** Complete

Built `app/services/salesiq_tools.py` with a `@tool` decorator pattern. 13 read-only tools covering all major entities (Customer, Note, Engagement, Milestone, Seller, Opportunity, Partner, ActionItem) and reports (Hygiene, Workload, What's New, Revenue Alerts, Whitespace).

Enforcement:
- `copilot-instructions.md` rule: "add a tool when adding a queryable entity or report"
- `tests/test_salesiq_tools.py::TestToolCoverage` - fails if a core entity or report is missing a tool
- `tests/test_salesiq_tools.py::TestToolExecution` - verifies tools actually run against the DB

Key exports: `get_openai_tools()`, `get_mcp_tools()`, `execute_tool(name, params)`

---

### Phase 2: Chat Endpoint (Backend + Gateway) - DONE

**Status:** Complete

Built the full chat pipeline: gateway `POST /v1/chat` endpoint with server-side system prompt construction, page validation (`VALID_PAGES` whitelist), and tool passthrough. Flask `POST /api/ai/chat` with multi-round tool-calling orchestration loop (max 3 rounds), local tool execution via the `salesiq_tools` registry, and token usage accumulation across rounds. Added `chat_completion_with_tools()` to `openai_client.py` and `CHAT_SYSTEM_PROMPT` to `prompts.py`. 13 tests in `tests/test_ai_chat.py`. Deployed to APIM staging and verified end-to-end with live tool calls.

**Original goal:** `POST /api/ai/chat` - the user sends a message, the backend orchestrates tool calls via Azure OpenAI, returns a final answer.

#### 2a. Gateway changes (`infra/gateway/`)

The gateway currently proxies single-shot prompt completions. For chat with tool calling, it needs:

- **New endpoint: `POST /ai/chat`** - accepts a full messages array + tool definitions (not just a prompt string)
- Routes to Azure OpenAI Chat Completions API with `tools` parameter
- Returns the model's response including any `tool_calls`
- The gateway does NOT execute tools - it just relays the model's tool call requests back to the Flask app
- Auth: same Entra JWT validation as existing endpoints

This is the simplest approach: the gateway stays thin (just a relay), and tool execution happens in the Flask app which has DB access.

#### 2b. Flask chat endpoint (`app/routes/ai.py`)

New route: `POST /api/ai/chat`

Request body:
```json
{
    "message": "What milestones are at risk for Contoso?",
    "history": [{"role": "user", "content": "..."}, ...],
    "context": {"page": "customer_view", "customer_id": 42}
}
```

**Validation:**
- `context` is required. Requests without a valid `page` field are rejected with 400. This prevents use as a generic chat proxy since you'd need to fabricate Sales Buddy page context.
- `message` max length: 2000 characters.
- `history` max length: 20 messages (older messages truncated from the front).

Flow:
1. Build system prompt with persona + page context (see 2c)
2. Send messages + `get_openai_tools()` to gateway `/ai/chat`
3. If response contains `tool_calls`, execute each via `execute_tool()`
4. Send tool results back to gateway for a final response
5. Return `{"reply": "...", "tools_used": [...]}`

Tool execution loop should cap at 3 rounds to prevent runaway chains.

#### 2c. System prompt construction (abuse prevention)

The system prompt is the primary guardrail against misuse. The gateway constructs it - callers cannot override it.

Build dynamically per request:
- **Persona + scope lock:** "You are a Sales Buddy assistant for Azure technical sellers. You ONLY answer questions about customers, engagements, milestones, notes, revenue, partners, and seller workload tracked in Sales Buddy. Politely decline any unrelated requests - you are not a general-purpose assistant."
- **Page context injection:** "The user is currently viewing customer Contoso (TPID 12345)..." - constructed from the `context` field in the request. This grounds the model's responses in the user's current workflow.
- **Behavioral rules:** Be concise, cite data from tool results, don't hallucinate, say when data is missing, never fabricate customer names or numbers.
- **Tool-only data access:** "Only reference data returned by tool calls. Do not guess or infer data that wasn't returned."

#### 2d. Testing

- Unit tests for system prompt construction
- Unit tests for the tool execution loop (mock gateway responses with tool_calls)
- Integration test: send a chat message, verify response includes tool_used

---

### Phase 3: Chat Panel UI (Dev-Only) - DONE

**Status:** Complete

Built chat flyout in `base.html` with SalesIQ branding, URL-based page context auto-detection, `window.copilotContext` overrides on key pages (customer_view, customers_list, milestone_view, seller_view), sessionStorage message history, Markdown rendering, typing indicator, and `config.DEBUG` dev gate. Fixed flyout stacking for 5+ levels.

**Goal:** A working chat panel in the browser, gated behind `FLASK_ENV=development` so it doesn't ship to production yet.

#### 3a. Toggle & panel shell

- Chat toggle button in navbar (sparkle/brain icon), only rendered when `FLASK_ENV == 'development'`
- Collapsible side panel (~450px), pinned to right edge
- Panel has: message input, send button, scrollable message area, close button

#### 3b. Message rendering

- User messages: right-aligned bubbles
- Assistant messages: left-aligned, rendered as Markdown (links, tables, lists, bold)
- Typing indicator (pulsing dots) while waiting for response
- Auto-scroll to newest message

#### 3c. Page context system

Each template emits a `window.copilotContext` object with page-specific data:
```js
window.copilotContext = {
    page: 'customer_view',
    customer_id: 42,
    customer_name: 'Contoso'
};
```

The chat JS includes this with every request. Context changes when the user navigates. Start with key pages: customer view, milestone tracker, engagement view, home dashboard.

#### 3d. Conversation management

- Message history stored in JS memory (resets on page navigation)
- History sent with each request so the model has conversational context
- Cap history at ~20 messages to stay within token limits
- "Clear conversation" button

#### 3e. Dev gate

- Template conditional: `{% if config.ENV == 'development' %}`
- Chat endpoint also checks `FLASK_ENV` and returns 404 in production
- Remove the gate in a future phase once the feature is stable

---

### Phase 4: More Entity & Report Tools - IN PROGRESS

**Status:** Tools built, but tool definitions need refinement for real-world chat queries (see validation list below)

Added 7 tools to `salesiq_tools.py` (total: 21 tools):
- `get_milestones_due_soon` - milestones due within N days with seller/team filters
- `get_territory_summary` - list all territories or get detail with customers, sellers, SEs, 30-day note count
- `get_pod_overview` - list all PODs or get detail with territories, sellers, solution engineers
- `get_analytics_summary` - call volume, active customers, top topics, neglected customers
- `report_one_on_one` - 1:1 prep: recent notes by customer, open engagements, committed milestones
- `search_contacts` - unified search across customer and partner contacts by name/email/title
- `get_revenue_customer_detail` - per-customer revenue by bucket with monthly history

All 7 tools have coverage tests in `TestToolCoverage` and execution tests in `TestToolExecution` (52 tests total, all passing).

#### Phase 4 polish (chat UX & prompt fixes) - DONE:
- Rebranded chat panel from "Copilot" to "SalesIQ"
- Replaced Copilot icon with `bi-chat-dots` Bootstrap icon
- Added markdown heading (h1-h4) and ordered list rendering
- Widened flyout to 500px, fixed CSS specificity bug in flyout stacking
- Compact header matching other flyouts, active button state when open
- Instant flyout restore on page nav (no slide animation on reload)
- Content filter detection: HAL 9000 icon + "I'm sorry Dave" response
- System prompt: added Sales Buddy terminology (milestones not "work items", notes not "call logs"), POD/territory/contact/analytics concepts, "use tools immediately" rule
- User identity injection from UserPreference (name, role), single-user app context
- Gateway deployed to staging with all prompt/context changes

#### Phase 4 remaining work: tool definition gaps

Testing revealed the model picks wrong tools or returns partial data for common questions. Known issues:

- `search_customers` returns up to 20 results but no `total_count` - model can't answer "how many customers do I have?"
- No tool returns aggregate counts (total customers, total notes, total engagements, total sellers)
- No tool lists sellers - `get_seller_workload` requires a known `seller_id`
- No tool surfaces "what should I work on today?" or priority-ranked items
- `search_notes` has no way to get "most recent N notes" without a keyword
- No tool for engagement listing/search (only `get_engagement_details` for a known ID)
- No tool for project listing or details
- Report tools return raw data but model struggles to summarize large result sets

#### Phase 4 validation queries

Test each query in the SalesIQ chat panel. For each, note whether the model picks the right tool, gets accurate data, and gives a useful answer. Queries marked with (GAP) are expected to fail or give poor results with the current toolset.

**Counting & overview questions:**
1. How many customers do I have? (GAP - no total count)
2. How many open engagements are there?  (GAP - no engagement count/list tool)
3. How many milestones are committed right now?
4. Who are my sellers? (GAP - no seller list tool)
5. Give me a quick summary of my portfolio
6. What territories do I cover?
7. How many PODs am I in?

**Customer-focused questions:**
8. What's going on with Contoso?
9. Which customers haven't had a note in 30 days?
10. Show me my top 5 customers by revenue
11. What customers does Sarah cover?
12. Which customers have open Fabric engagements?
13. What's the revenue trend for Contoso over the last 6 months?

**Engagement & milestone questions:**
14. What milestones are due this week?
15. What's at risk right now?
16. Show me all committed milestones for Q3
17. Which engagements are stalled? (GAP - no engagement search/filter)
18. What did we close last month?
19. List open action items across all engagements

**Notes & activity questions:**
20. What did I talk about with Fabrikam last time?
21. Show me my most recent notes (GAP - no "recent notes" without keyword)
22. What topics have come up the most this quarter?
23. When was my last call with Contoso?
24. Search my notes for anything about Cosmos DB

**Prep & planning questions:**
25. Prep me for my 1:1
26. What should I focus on today? (GAP - no priority/recommendation tool)
27. I have a meeting with Contoso in an hour - what do I need to know?
28. Fill my day - what customers need attention?
29. What's new since last Friday?

**Revenue & whitespace questions:**
30. Which customers have declining revenue?
31. Where's my whitespace?
32. What Fabric opportunities am I missing?
33. Show me revenue alerts

**Partner & contact questions:**
34. Find me the contact at Contoso who works on data
35. Which partners specialize in Fabric?
36. What partners have we worked with recently? (GAP - no partner activity tool)

**Cross-cutting / complex questions:**
37. Compare Sarah's workload to mine
38. Which territories are understaffed? (GAP - no workload-per-territory tool)
39. What hygiene issues do I need to clean up?
40. Summarize everything that happened last week

---

### Phase 5: MCP Server

**Goal:** Let VS Code Copilot query SalesBuddy data directly via MCP protocol.

#### 5a. Server implementation (`app/mcp_server.py`)

- Uses the `mcp` Python SDK (`pip install mcp`)
- Registers tools from `get_mcp_tools()`
- Tool handlers call `execute_tool()` within a Flask app context
- stdio transport for local VS Code usage
- Read-only tools only (no write actions without UI confirmation)

#### 5b. VS Code integration

User adds to `.vscode/mcp.json`:
```json
{
    "servers": {
        "salesbuddy": {
            "command": "python",
            "args": ["-m", "app.mcp_server"],
            "cwd": "C:\\dev\\SalesBuddy"
        }
    }
}
```

Then VS Code Copilot can call tools like `search_notes`, `get_customer_summary`, etc. directly in chat.

#### 5c. MCP Resources (stretch)

Expose entities as MCP resources for richer context:
- `salesbuddy://customer/{id}`
- `salesbuddy://engagement/{id}`
- `salesbuddy://milestone/{id}`

---

### Phase 6: Write Tools with Confirmation

**Goal:** Let the chat modify data (update engagement status, add comments, create notes) with a confirmation step.

- Write tools get a `requires_confirmation: true` flag in the registry
- Chat endpoint returns pending actions instead of executing immediately
- Panel shows a confirmation card ("I'll mark Fabric POC as Won. Confirm?")
- User clicks confirm, panel sends `POST /api/ai/chat/confirm` to execute
- Requires careful UX - only after the read-only experience is solid

---

## Open Questions

- Should the chat panel be available on every page or only certain pages?
- Rate limiting on the chat endpoint? (Probably yes - same as other AI features)
- MCP: stdio only, or also SSE for potential remote access?

## Architecture

```
Browser (Chat Panel)          VS Code (MCP Client)
        |                              |
        | POST /api/ai/chat            | stdio/SSE
        v                              v
  Flask Backend               MCP Server (app/mcp_server.py)
        |                              |
        +--------- Shared Tool Registry --------+
                  app/services/salesiq_tools.py
                         |
                   Existing service layer
                   (models, queries, routes)
```

## Key Files

- `app/services/salesiq_tools.py` - Tool definitions + handler functions (shared)
- `app/routes/ai.py` - `POST /api/ai/chat` endpoint (chat panel backend)
- `app/mcp_server.py` - MCP server for VS Code/external clients
- `templates/partials/_chat_panel.html` - Chat panel UI partial
- `static/js/chat-panel.js` - Chat panel client-side logic (optional, could be inline)

## Resume Context

**Last completed:** Phase 3 (chat panel UI) and Phase 4 polish (UX/prompt fixes) - merged to main.
**In progress:** Phase 4 tool definitions - 21 tools built but validation queries exposed gaps in counting, listing, and cross-entity queries. See validation query list above.

**Next up:** Phase 2 (chat endpoint). Start with 2a (gateway `POST /ai/chat`) then 2b (Flask `POST /api/ai/chat` with tool execution loop).

**Key design decisions made:**
- System prompt is the primary abuse guardrail (scope-locked persona, topic restriction)
- `context` field is required on all chat requests (prevents generic proxy use)
- Gateway stays thin (relay only) - tool execution happens in Flask which has DB access
- Chat panel is dev-gated (`FLASK_ENV=development`) in Phase 3

**Existing gateway pattern to follow:** See `infra/gateway/gateway.py` for current endpoints and `app/gateway_client.py` for how the Flask app calls the gateway. The new `/ai/chat` endpoint follows the same auth pattern (Entra JWT via APIM).

**13 tools already registered in `app/services/copilot_tools.py`:**
search_customers, get_customer_summary, search_notes, get_engagement_details, get_milestone_status, get_seller_workload, get_opportunity_details, search_partners, list_action_items, report_hygiene, report_workload, report_whats_new, report_revenue_alerts, report_whitespace

## Architecture Reference
