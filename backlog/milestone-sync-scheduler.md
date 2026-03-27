# Migrate Milestone Sync to In-Process Scheduler

## Summary

Replace the Windows Scheduled Task that triggers milestone sync with an in-process daemon thread (same pattern as Copilot daily action items). This eliminates a Windows dependency and adds missed-sync catchup on startup.

## Current State

- `scripts/server.ps1` registers a Windows Scheduled Task at a random time (to stagger users)
- The task runs `scripts/milestone-sync.ps1` which hits the SSE endpoint
- Flask handles the actual sync as a generator
- If the server is off when the task fires, the sync is silently skipped

## Proposed Changes

### 1. Random Sync Time

- On first run: generate a random hour + minute (e.g. between 5:00 AM and 8:00 AM) and store it in `UserPreference` (e.g. `milestone_sync_hour`, `milestone_sync_minute`)
- This preserves the staggering behavior so all Sales Buddy instances don't slam MSX at the same time
- User can see (but not edit) their scheduled time in admin panel

### 2. In-Process Daemon Thread

- Same pattern as `start_daily_scheduler()` in copilot_actions.py
- Background thread sleeps in a loop, checks if current time matches the stored sync time
- Fires the sync once per day at that time
- Track `last_milestone_sync` in UserPreference (like `last_copilot_sync`)

### 3. Startup Catchup

- On app start, check `last_milestone_sync` against today's scheduled time
- If the sync was missed (server was off), trigger immediately
- Same pattern as `start_copilot_sync_background()`

### 4. Enable/Disable Toggle

- Add `milestone_auto_sync` boolean to UserPreference (default True)
- Admin panel toggle to enable/disable auto-sync
- The daemon thread checks this before running
- Manual sync button still works regardless of this toggle

### 5. Remove Windows Scheduled Task

- Remove the milestone sync task registration from `scripts/server.ps1`
- Remove `scripts/milestone-sync.ps1` (no longer needed as external trigger)
- The SSE endpoint stays (manual sync still uses it)

## Benefits

- No Windows Task Scheduler dependency
- Missed syncs caught up on startup
- Staggered timing preserved via random stored time
- User control via admin toggle
- One less external script to maintain

## Open Questions

- Should the random time be editable by the user?
- Should we keep the Windows task as a fallback for the first release?
- Do we need a "last sync" indicator in the admin panel?

## Priority

Medium - current approach works but has the missed-sync gap
