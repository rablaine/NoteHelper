# Test Suite Audit — Consolidation TODO

**Created:** March 8, 2026
**Current count:** ~1,000+ tests across 14 test files
**Estimated after cleanup:** ~870–900 tests (same coverage, less duplication)

---

## 1. Quick Wins (Dead Code / Exact Dupes)

### Delete `test_eager_loading.py` entirely (11 tests)
All 11 tests are exact duplicates of tests in `test_views.py` or `test_forms.py`. They just GET a page and assert `200` + a string — identical to existing view tests.

| Eager loading test | Already covered by |
|---|---|
| `test_seller_view_customers_sorted` | `test_views::test_seller_view_loads` |
| `test_customer_view_notes_sorted` | `test_views::test_customer_view_loads` |
| `test_topic_view_notes_sorted` | `test_views::test_topic_view_loads` |
| `test_territory_view_sellers_sorted` | `test_views::test_territory_view_loads` |
| `test_customer_form_seller_customers_sorted` | `test_forms::test_customer_create_form_loads` |
| `test_customer_form_territory_sellers` | `test_forms::test_customer_create_with_territory_preselect` |
| `test_customer_view_topics_count` | subset of `test_views::test_customer_view_loads` |
| `test_note_view_topics_iteration` | `test_views::test_note_view_loads` |
| `test_seller_view_territories_length` | `test_views::test_seller_view_with_territories` |
| `test_territory_view_seller_customers_count` | `test_views::test_territory_view_loads` |
| `test_note_form_topics_sorted` | `test_forms::test_note_create_form_loads` |

### Delete `test_config.py` (0 tests)
Orphaned config file with zero test methods. Actual test config lives in `conftest.py`.

### Remove 2 dead `pass`-only stubs in `test_api.py`
- `test_topic_autocomplete` — body is just `pass`, comment says "not yet implemented"
- `test_topic_autocomplete_empty_query` — same

### Remove 1 exact duplicate in `test_integration.py`
- `test_note_create_post` and `test_note_create_succeeds` test the exact same thing

---

## 2. Parametrize Candidates (30–40 tests → ~10)

### Preference GET/POST pairs in `test_api.py` (8 → 2)
Four preferences each have separate GET and POST tests. Combine into `@pytest.mark.parametrize`:
- `test_dark_mode_preference_get` / `_post`
- `test_customer_view_preference_get` / `_post`
- `test_topic_sort_preference_get` / `_post`
- `test_show_customers_without_calls_preference_get` / `_post`

### Admin consent check variants in `test_views.py` (3 → 1)
- `test_admin_ai_consent_check_endpoint_ok`
- `test_admin_ai_consent_check_endpoint_needs_relogin`
- `test_admin_ai_consent_check_endpoint_error`

Same endpoint, different mock returns — perfect parametrize.

### Update check variants in `test_views.py` (3 → 1)
- `test_update_check_includes_boot_commit`
- `test_update_check_restart_needed_when_commits_differ`
- `test_update_check_no_restart_when_boot_commit_none`

Same structure, different config/mock values.

### Date parser tests in `test_milestone_tracker.py` (4 → 1)
- `test_parse_iso_date_with_z`, `test_parse_none_returns_none`, `test_parse_empty_returns_none`, `test_parse_invalid_returns_none`

### OneDrive detection in `test_note_backup.py` (5 → 1-2)
- Five tests for OneDrive path classification with different path strings

### Connect export validation in `test_export_import.py` (5 → 1-2)
- `test_requires_json`, `test_requires_name`, `test_requires_dates`, `test_rejects_invalid_dates`, `test_rejects_reversed_dates`

---

## 3. Overly Granular (25–30 tests consolidatable)

### Analytics page tests in `test_analytics.py` (5 → 1-2)
Five tests all GET `/analytics` with `sample_data` and check for different `<b>` strings on the same page:
- `test_analytics_page_loads`, `test_analytics_shows_key_metrics`, `test_analytics_call_frequency_trend`, `test_analytics_seller_activity`, `test_analytics_quick_actions`

Could be one test that checks all expected sections.

### Connect export page load tests (5 → 1-2)
- `test_page_loads`, `test_page_has_form`, `test_default_end_date_is_today`, `test_back_to_admin_link`, `test_no_previous_exports_initially`

All GET the same page, check different elements.

### Onboarding wizard element checks (~15-20 → ~5-7)
Example: 7 separate tests all check step 2 HTML elements. Could be 1-2 tests per wizard step.

---

## 4. Cross-File Overlap (~15 tests)

| Test | Overlaps with |
|---|---|
| `test_ux_improvements::test_admin_panel_stats_are_clickable` | `test_views` admin panel tests |
| `test_ux_improvements::test_topics_toggle_shows_current_state` | `test_views::test_topics_list_*` |
| `test_ux_improvements::test_customers_filter_toggle_button` | `test_views::test_customers_list_filters_without_calls` |
| `test_ai::test_connection_test_*` | `test_views::test_admin_ai_test_*` |
| `test_ai::test_audit_log_success` / `_failure` | `test_ai::TestGenerateEngagementSummary` audit log tests |
| `test_telemetry` + `test_telemetry_aggregation` | Some event creation overlap (~8-10) |

---

## Summary

| Category | Tests affected | Net reduction |
|---|---|---|
| Dead code / exact dupes | ~14 | -14 |
| Parametrize | ~30-40 | -20-30 |
| Consolidate granular | ~25-30 | -15-20 |
| Cross-file overlap | ~15 | -10-15 |
| **Total** | | **~60-80 fewer tests** |

All the useful tests are genuinely useful. This is about DRY-ing up the test suite, not removing coverage.
