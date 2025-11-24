# Single-User Mode Conversion - Implementation Plan

## Status: IN PROGRESS
Created: November 23, 2025

## Overview
Converting NoteHelper from multi-user Azure AD OAuth to single-user local mode.
This involves removing authentication, user isolation, and simplifying to a single default user.

## Scope Analysis
- **526 total references** to user-related code
  - 197 current_user references
  - 136 user_id parameter references  
  - 111 user_id filter_by() calls
  - 72 @login_required decorators
  - 10 is_admin checks

## Implementation Strategy

###  Phase 1: Core Infrastructure (THIS FILE)
**Goal:** Remove authentication system, create single default user

**Files to modify:**
1. `app/__init__.py` - Remove Flask-Login, create default user on startup
2. `app/models.py` - Simplify User model, keep single user row
3. `requirements.txt` - Remove msal, Flask-Login

**Steps:**
1. Remove Flask-Login initialization
2. Remove Azure AD config
3. Remove auth blueprint registration
4. Remove before_request user checks
5. Create single default user on app startup
6. Create single default preferences on startup

### Phase 2: Remove user_id Filters (AUTOMATED)
**Goal:** Remove all `.filter_by(user_id=...)` calls

**Script approach:**
```python
# Find all: .filter_by(user_id=current_user.id)
# Replace with: no filter (returns all records)

# Before:
Customer.query.filter_by(user_id=current_user.id).all()
# After:
Customer.query.all()
```

**Files affected (111 occurrences):**
- app/routes/call_logs.py
- app/routes/customers.py
- app/routes/sellers.py
- app/routes/territories.py
- app/routes/topics.py
- app/routes/pods.py
- app/routes/solution_engineers.py
- app/routes/main.py
- app/routes/ai.py

### Phase 3: Remove @login_required (AUTOMATED)
**Goal:** Remove all authentication decorators

**Script approach:**
```python
# Find lines with: @login_required
# Delete those lines

# Also remove imports:
from flask_login import login_required, current_user
```

**Files affected (72 occurrences):**
- All route files in app/routes/

### Phase 4: Replace current_user with Single User
**Goal:** Get single user from database instead of session

**Create helper in models.py:**
```python
def get_single_user():
    """Get the single default user."""
    return User.query.first()
```

**Replace patterns:**
```python
# Before:
new_call = CallLog(user_id=current_user.id, ...)
# After:
user = get_single_user()
new_call = CallLog(user_id=user.id, ...)

# Or simplify further by removing user_id entirely from new records
```

### Phase 5: Remove Admin Checks
**Goal:** Everyone is admin in single-user mode

**Remove patterns:**
```python
# Delete these checks:
if not current_user.is_admin:
    flash('Access denied', 'danger')
    return redirect(url_for('main.index'))
```

### Phase 6: Simplify Preferences
**Goal:** App-wide preferences instead of per-user

**Changes:**
- UserPreference becomes AppPreference (single row)
- Remove user_id foreign key
- Load preferences once at app startup into g.prefs

### Phase 7: Remove Auth Routes
**Goal:** Delete entire auth blueprint

**Delete files:**
- app/routes/auth.py (entire file - 461 lines)
- templates/login.html
- templates/user_profile.html
- templates/first_time_flow.html
- templates/account_link_status.html
- templates/domain_not_allowed.html

### Phase 8: Update Templates
**Goal:** Remove user UI elements

**Changes:**
- base.html: Remove user menu, login/logout
- Remove "Logged in as..." displays
- Remove account linking UI
- Keep preferences but make them app-wide

### Phase 9: Clean Up Models
**Goal:** Simplify database schema

**Keep but simplify:**
- User (single row, no Azure IDs)
- UserPreference → AppPreference

**Remove entirely:**
- WhitelistedDomain
- AccountLinkingRequest  
- User.microsoft_azure_id
- User.external_azure_id
- User.is_stub
- User.linked_at

### Phase 10: Update Tests
**Goal:** Remove auth tests, update fixtures

**Changes:**
- Delete tests/test_account_linking.py
- Update conftest.py to create single default user
- Remove login simulation in tests
- Update all test queries to not filter by user_id

## Automated Replacement Script

See: `convert_to_single_user.py` (to be created)

This script will:
1. Remove @login_required decorators
2. Remove login_required imports
3. Replace .filter_by(user_id=current_user.id) with no filter
4. Replace current_user.id with get_single_user().id
5. Remove is_admin checks
6. Generate report of manual changes needed

## Manual Changes Required

After running automated script:

1. **app/__init__.py** - Rewrite to remove Flask-Login
2. **app/models.py** - Simplify User model
3. **templates/base.html** - Remove user menu
4. **app/routes/main.py** - Update preferences handling
5. **tests/conftest.py** - Create single user fixture

## Testing Checklist

After conversion:
- [ ] App starts without errors
- [ ] Database creates single default user
- [ ] All CRUD operations work
- [ ] Search and filters work
- [ ] Import/export works
- [ ] AI features work (if keeping them)
- [ ] All tests pass
- [ ] No user_id filter errors in logs

## Estimated Time

- Automated replacements: 30 min
- Manual code updates: 2 hours
- Template updates: 1 hour
- Test updates: 1 hour
- Testing and fixes: 1 hour
- **Total: 5-6 hours**

## Next Steps

1. Create `convert_to_single_user.py` automation script
2. Run script to do bulk replacements  
3. Manually fix app/__init__.py and models.py
4. Update templates
5. Fix tests
6. Test thoroughly
7. Commit to feature branch

