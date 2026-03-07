# Issue #23: Account Sync Upsert Strategy

**Status:** Shelved (analysis complete, implementation pending)
**Date:** March 5, 2026

## Problem

Throughout the year, mergers/acquisitions and seller changes cause customer data to shift in MSX. The current account sync (`import_stream`) only creates new records. When an existing TPID is found, the sync skips it entirely (except for backfilling a missing `tpid_url`). This means name changes, territory reassignments, seller changes, and vertical updates are silently ignored.

## Current Behavior

| Entity | Matched By | If Exists... |
|---|---|---|
| Customer | TPID | **Skipped** (name, territory, seller, verticals all ignored) |
| Territory | name | Reused (won't update pod assignment) |
| Seller | name | Reused (won't update seller_type or alias) |
| SE | name + specialty | Reused (won't update alias) |
| Vertical | name | Reused (fine, name is the only field) |
| POD | name | Reused (fine, name is the only field) |

## Proposed Upsert Strategy

### Safe Auto-Updates (no user confirmation needed)

- `tpid_url` (already partially implemented)
- Vertical associations (additive, low risk)
- Territory assignment (MSX is authoritative)
- Seller assignment (MSX is authoritative)
- Seller alias and seller_type updates
- SE alias updates

### Needs User Attention (flag for review)

- Customer **name** changed: could be a rebrand (M&A) or a TPID reassignment. Update automatically but surface in the sync summary so the user knows.

### Never Auto-Change

- Never delete call logs or break the customer-to-call_log FK. TPID is the anchor that preserves data integrity.
- Never auto-delete customers that are no longer in MSX (they may have call logs).

### Key Considerations

- MSX account GUIDs are the primary keys on the backend, but TPID is the unique logical key in NoteHelper.
- If we're not positive about a change, ask the user to validate.
- The "move call logs between customers/TPIDs" feature is a separate UI workflow, not part of the sync.

## Affected Code Paths

1. **`app/routes/msx.py` > `import_stream()`** (line ~1044): The main SSE streaming import. This is the primary path to update.
2. **`app/routes/msx.py` > `import_accounts()`** (line ~789): The non-streaming JSON import endpoint. Same skip logic.

## Implementation Notes

- The customer loop currently does `if tpid in existing_tpids: customers_skipped += 1; continue`
- Change to: fetch the existing customer, compare fields, update what changed, track in a `customers_updated` counter
- Pre-load existing customers by TPID into a dict (not just a set) so we have the objects for comparison
- Report changes in the SSE progress stream and final summary
- Add a `last_synced_at` timestamp to Customer model to track freshness
