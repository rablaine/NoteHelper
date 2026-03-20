# Internal Projects

## Summary

Add a way to track internal projects (non-customer work) with notes and tasks, similar to engagements but without a customer association.

## Problem

Sellers have internal initiatives (training programs, tooling improvements, team processes, etc.) that need tracking but don't map to a customer. Currently the only option is creating notes without a customer, but there's no way to group them into a project with tasks and progress tracking.

## Proposed Solution

### New Model: `Project`

- `id` (int, PK)
- `title` (str, required)
- `description` (text, optional)
- `status` (str) - e.g. Active, On Hold, Completed
- `created_at`, `updated_at` (datetime)
- `seller_id` (FK to sellers, optional - owner/lead)
- Relationships: notes, tasks

### Integration Points

- **Notes**: Projects can have associated notes (like engagements do). Reuse the existing note system with a `project_id` FK on Note.
- **Tasks**: Projects can have tasks. Consider mixing project tasks into the existing Action Items card on the dashboard, or keep them separate.
- **Engagements hub**: Possibly add projects as a tab or section alongside engagements, since the workflow is similar (group of notes + tasks + status tracking).
- **Dashboard**: Surface open project tasks in the Action Items card alongside engagement tasks.

### Open Questions

- [ ] Should projects live in the engagements hub or get their own hub page?
- [ ] Should project tasks appear in the existing Action Items card or stay separate?
- [ ] Do projects need a due date / timeline?
- [ ] Should projects support multiple sellers (team-based)?
- [ ] Do projects need tags/topics like notes do?
- [ ] Any reporting or analytics needed for project tracking?

### UI Sketch

- **Projects list page** - table/card view of all projects with status, note count, task count
- **Project view page** - detail page with description, associated notes, tasks, activity timeline
- **Project form** - create/edit with title, description, status, owner

### Migration

- Add `Project` model to `models.py`
- Add `project_id` FK to `Note` model (nullable)
- Add project routes blueprint in `app/routes/projects.py`
- Add templates: `projects_list.html`, `project_view.html`, `project_form.html`

## Priority

Low - spec out when time permits

## Status

Draft - needs refinement
