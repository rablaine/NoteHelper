# SalesIQ - Remaining Work

## Tool Definition Gaps (Phase 4)

Testing revealed the model picks wrong tools or returns partial data for common questions. These need new or improved tools:

### New tools needed

- **`get_portfolio_overview`** - Aggregate counts: total customers, engagements, milestones, sellers, recent activity. Kills validation queries 1-7 in one call.
- **`list_sellers`** - List all sellers with basic stats. Currently `get_seller_workload` requires a known `seller_id`.
- **`search_engagements`** - Filter engagements by status, customer, seller, topic. Currently only `get_engagement_details` exists for a known ID.

### Existing tool improvements

- **`search_customers`** - Add `total_count` to response so the model can answer "how many customers do I have?"
- **`search_notes`** - Support "most recent N" without requiring a keyword.

### Architecture note

Most query logic lives inline in route handlers. Tools duplicate those queries independently. When touching these tools, extract shared query logic into `app/services/` so both routes and tools call the same functions. Don't refactor everything at once - do it as each tool is built/improved.

## Validation Queries

Test each in the SalesIQ chat panel. Queries marked (GAP) need the tools above.

**Counting & overview:** (1) How many customers? (GAP) (2) How many open engagements? (GAP) (3) Committed milestones count? (4) Who are my sellers? (GAP) (5) Portfolio summary (GAP) (6) What territories? (7) How many PODs?

**Customer:** (8) What's going on with Contoso? (9) Customers without notes in 30 days? (10) Top 5 by revenue? (11) What customers does Sarah cover? (12) Customers with open Fabric engagements? (13) Revenue trend for Contoso?

**Engagement & milestone:** (14) Milestones due this week? (15) What's at risk? (16) Committed milestones for Q3? (17) Stalled engagements? (GAP) (18) What closed last month? (19) Open action items?

**Notes & activity:** (20) Last call with Fabrikam? (21) Most recent notes? (GAP) (22) Top topics this quarter? (23) Last call with Contoso? (24) Notes about Cosmos DB?

**Prep & planning:** (25) Prep for 1:1? (26) What to focus on today? (27) Meeting with Contoso in an hour? (28) Fill my day? (29) What's new since Friday?

**Revenue & whitespace:** (30) Declining revenue customers? (31) Whitespace? (32) Fabric opportunities missing? (33) Revenue alerts?

**Partner & contact:** (34) Contact at Contoso who works on data? (35) Partners specializing in Fabric? (36) Partners worked with recently?

**Cross-cutting:** (37) Compare Sarah's workload to mine? (38) Understaffed territories? (39) Hygiene issues? (40) Summary of last week?

## Future Work

- **Documentation** - README section + Admin Panel link once tools are refined and SalesIQ is ungated from dev

### MCP Resources: Domain Ontology

The agent currently relies on tool names and descriptions to figure out what exists and how things connect. That's flat - it doesn't know that a customer *has* engagements, which *have* milestones, which *link to* opportunities. A seller *belongs to* a territory, which *belongs to* a POD. This causes wrong tool selection and multi-step query failures.

**Solution:** Use MCP Resources (`resources/list` / `resources/read`) to expose on-demand reference data the agent can pull when it needs orientation, instead of stuffing everything into the system prompt.

**Resources to build:**

1. **`salesbuddy://domain-model`** - Entity-relationship graph describing all entities, how they connect, cardinality, and which tools operate on each entity. Structured JSON or markdown. The agent reads this once per session to understand what's queryable and how to chain tools.

2. **`salesbuddy://glossary`** - Domain-specific term definitions. "Milestone" means an MSX sales opportunity tracked in Dynamics, not a project checkpoint. "Engagement" is an active workstream, not an email interaction. "POD" is an organizational group containing territories. Prevents the agent from misinterpreting user questions.

3. **`salesbuddy://workflows`** (optional) - Common intent-to-tool-chain mappings. "Prep for a 1:1" = `get_seller_workload` then `report_one_on_one`. "Deep dive on a customer" = `search_customers` then `get_customer_summary` then `get_revenue_customer_detail`. Helps the agent plan multi-tool sequences.

**Implementation:** Add `@mcp.list_resources()` and `@mcp.read_resource()` handlers to `app/mcp_server.py`. Content can live in a new `app/services/salesiq_ontology.py` module or inline in the MCP server. The domain model resource should be auto-generated from the tool registry + model relationships where possible so it stays in sync.

**Also consider MCP Resource Templates** (`resources/templates/list`) for parameterized lookups like `salesbuddy://entity/{type}` that return the schema, relationships, and available tools for a specific entity type on demand.

**MCP Prompts** (`prompts/list` / `prompts/get`) are another option for pre-wired intent resolution - reusable prompt templates like `prep_one_on_one(seller_name)` that tell the agent exactly which tools to call and in what order. Less about ontology, more about canned workflows.

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
