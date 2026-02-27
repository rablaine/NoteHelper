"""
Milestone sync service for NoteHelper.

Pulls active (uncommitted) milestones from MSX for all customers
and upserts them into the local database. Designed to be triggered
manually via button or on a schedule (e.g., 3 AM daily).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Generator

from app.models import db, Customer, Milestone, Opportunity, User
from app.services.msx_api import (
    extract_account_id_from_url,
    get_milestones_by_account,
    get_my_milestone_team_ids,
    build_milestone_url,
)

logger = logging.getLogger(__name__)

# Active milestone statuses (uncommitted — the ones we're working to commit)
ACTIVE_STATUSES = {'On Track', 'At Risk', 'Blocked'}


def sync_all_customer_milestones(user_id: int) -> Dict[str, Any]:
    """
    Sync active milestones from MSX for all customers with a tpid_url.
    
    Loops through every customer that has an MSX account link (tpid_url),
    fetches their milestones from MSX, and upserts into the local database.
    
    Args:
        user_id: The user ID to associate with new milestones.
        
    Returns:
        Dict with sync results:
        - success: bool
        - customers_synced: int (customers successfully queried)
        - customers_skipped: int (customers without tpid_url)
        - customers_failed: int (customers where MSX query failed)
        - milestones_created: int
        - milestones_updated: int
        - milestones_deactivated: int (marked as no longer active in MSX)
        - errors: list of error strings
        - duration_seconds: float
    """
    start_time = datetime.now(timezone.utc)
    
    results = {
        "success": True,
        "customers_synced": 0,
        "customers_skipped": 0,
        "customers_failed": 0,
        "milestones_created": 0,
        "milestones_updated": 0,
        "milestones_deactivated": 0,
        "errors": [],
        "duration_seconds": 0,
    }
    
    # Get all customers with MSX account links
    customers = Customer.query.filter(
        Customer.tpid_url.isnot(None),
        Customer.tpid_url != '',
    ).all()
    
    if not customers:
        results["success"] = True
        results["errors"].append("No customers with MSX account links found.")
        return results
    
    logger.info(f"Starting milestone sync for {len(customers)} customers")
    
    for customer in customers:
        try:
            customer_result = sync_customer_milestones(customer, user_id)
            
            if customer_result["success"]:
                results["customers_synced"] += 1
                results["milestones_created"] += customer_result["created"]
                results["milestones_updated"] += customer_result["updated"]
                results["milestones_deactivated"] += customer_result["deactivated"]
            else:
                results["customers_failed"] += 1
                results["errors"].append(
                    f"{customer.get_display_name()}: {customer_result['error']}"
                )
        except Exception as e:
            results["customers_failed"] += 1
            results["errors"].append(
                f"{customer.get_display_name()}: {str(e)}"
            )
            logger.exception(f"Error syncing milestones for customer {customer.id}")
    
    # Calculate duration
    results["duration_seconds"] = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    # If all customers failed, mark as failure
    if results["customers_synced"] == 0 and results["customers_failed"] > 0:
        results["success"] = False
    
    # Update team membership flags
    _update_team_memberships()
    
    logger.info(
        f"Milestone sync complete: {results['customers_synced']} synced, "
        f"{results['customers_failed']} failed, "
        f"{results['milestones_created']} created, "
        f"{results['milestones_updated']} updated"
    )
    
    return results


def sync_all_customer_milestones_stream(
    user_id: int,
) -> Generator[str, None, None]:
    """
    Stream milestone sync progress as Server-Sent Events.

    Yields SSE-formatted strings with progress updates per customer.
    Event types:
        - start: total customer count
        - progress: per-customer result
        - complete: final summary

    Args:
        user_id: The user ID to associate with new milestones.
    """
    start_time = datetime.now(timezone.utc)

    customers = Customer.query.filter(
        Customer.tpid_url.isnot(None),
        Customer.tpid_url != '',
    ).all()

    total = len(customers)
    if total == 0:
        yield _sse_event('complete', {
            'success': True,
            'total': 0,
            'synced': 0,
            'failed': 0,
            'created': 0,
            'updated': 0,
            'message': 'No customers with MSX account links found.',
        })
        return

    yield _sse_event('start', {'total': total})

    synced = 0
    failed = 0
    total_created = 0
    total_updated = 0
    total_deactivated = 0
    errors = []

    for i, customer in enumerate(customers, 1):
        name = customer.get_display_name()
        try:
            result = sync_customer_milestones(customer, user_id)
            if result['success']:
                synced += 1
                total_created += result['created']
                total_updated += result['updated']
                total_deactivated += result['deactivated']
                yield _sse_event('progress', {
                    'current': i,
                    'total': total,
                    'customer': name,
                    'status': 'ok',
                    'created': result['created'],
                    'updated': result['updated'],
                })
            else:
                failed += 1
                errors.append(f"{name}: {result['error']}")
                yield _sse_event('progress', {
                    'current': i,
                    'total': total,
                    'customer': name,
                    'status': 'error',
                    'error': result['error'],
                })
        except Exception as e:
            failed += 1
            errors.append(f"{name}: {str(e)}")
            logger.exception(f"Error syncing milestones for customer {customer.id}")
            yield _sse_event('progress', {
                'current': i,
                'total': total,
                'customer': name,
                'status': 'error',
                'error': str(e),
            })

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    # Update team membership flags (one extra API call)
    _update_team_memberships()

    yield _sse_event('complete', {
        'success': synced > 0 or failed == 0,
        'total': total,
        'synced': synced,
        'failed': failed,
        'created': total_created,
        'updated': total_updated,
        'deactivated': total_deactivated,
        'duration': round(duration, 1),
        'errors': errors[:5],
    })


def _sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """Format a dict as a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def sync_customer_milestones(
    customer: Customer,
    user_id: int,
) -> Dict[str, Any]:
    """
    Sync milestones from MSX for a single customer.
    
    Fetches active milestones from MSX and upserts them into the database.
    Milestones that are no longer returned by MSX (e.g., completed/cancelled)
    get their status updated.
    
    Args:
        customer: The Customer model instance.
        user_id: The user ID to associate with new milestones.
        
    Returns:
        Dict with:
        - success: bool
        - created: int
        - updated: int
        - deactivated: int
        - error: str (if failed)
    """
    result = {"success": False, "created": 0, "updated": 0, "deactivated": 0, "error": ""}
    
    # Extract account ID from the customer's tpid_url
    account_id = extract_account_id_from_url(customer.tpid_url)
    if not account_id:
        result["error"] = "Could not extract account ID from tpid_url"
        return result
    
    # Fetch milestones from MSX — only from open opportunities and current
    # fiscal year to exclude stale milestones
    msx_result = get_milestones_by_account(
        account_id,
        open_opportunities_only=True,
        current_fy_only=True,
    )
    if not msx_result.get("success"):
        result["error"] = msx_result.get("error", "Unknown MSX error")
        return result
    
    msx_milestones = msx_result.get("milestones", [])
    now = datetime.now(timezone.utc)
    
    # Track which MSX milestone IDs we saw from MSX
    seen_msx_ids = set()
    
    for msx_ms in msx_milestones:
        msx_id = msx_ms.get("id")
        if not msx_id:
            continue
        
        seen_msx_ids.add(msx_id)
        
        # Parse due date if present
        due_date = _parse_msx_date(msx_ms.get("due_date"))
        
        # Upsert the parent Opportunity if we have an opportunity GUID
        opportunity = _upsert_opportunity(
            msx_ms, customer.id, user_id
        )
        
        # Find existing milestone or create new one
        milestone = Milestone.query.filter_by(msx_milestone_id=msx_id).first()
        
        if milestone:
            # Update existing milestone with latest data from MSX
            _update_milestone_from_msx(milestone, msx_ms, customer.id, due_date, now)
            if opportunity:
                milestone.opportunity_id = opportunity.id
            result["updated"] += 1
        else:
            # Create new milestone
            milestone = _create_milestone_from_msx(
                msx_ms, customer.id, user_id, due_date, now,
                opportunity_id=opportunity.id if opportunity else None,
            )
            db.session.add(milestone)
            result["created"] += 1
    
    # Deactivate milestones for this customer that are no longer in MSX
    # (They may have been completed, cancelled, etc.)
    existing_milestones = Milestone.query.filter_by(customer_id=customer.id).filter(
        Milestone.msx_milestone_id.isnot(None),
        Milestone.msx_status.in_(ACTIVE_STATUSES),
    ).all()
    
    for existing in existing_milestones:
        if existing.msx_milestone_id not in seen_msx_ids:
            # Skip milestones linked to call logs — keep them visible
            if existing.call_logs:
                existing.last_synced_at = now
                continue
            # This milestone wasn't returned by MSX — mark as potentially completed
            existing.msx_status = "Completed"
            existing.last_synced_at = now
            result["deactivated"] += 1
    
    try:
        db.session.commit()
        result["success"] = True
    except Exception as e:
        db.session.rollback()
        result["error"] = f"Database error: {str(e)}"
        logger.exception(f"Error saving milestones for customer {customer.id}")
    
    return result


def _update_milestone_from_msx(
    milestone: Milestone,
    msx_data: Dict[str, Any],
    customer_id: int,
    due_date: Optional[datetime],
    now: datetime,
) -> None:
    """Update an existing milestone with fresh data from MSX."""
    milestone.title = msx_data.get("name") or milestone.title
    milestone.milestone_number = msx_data.get("number") or milestone.milestone_number
    milestone.msx_status = msx_data.get("status") or milestone.msx_status
    milestone.msx_status_code = msx_data.get("status_code")
    milestone.opportunity_name = msx_data.get("opportunity_name") or milestone.opportunity_name
    milestone.workload = msx_data.get("workload") or milestone.workload
    milestone.monthly_usage = msx_data.get("monthly_usage")
    milestone.due_date = due_date
    milestone.dollar_value = msx_data.get("dollar_value")
    milestone.url = msx_data.get("url") or milestone.url
    milestone.customer_id = customer_id
    milestone.last_synced_at = now


def _create_milestone_from_msx(
    msx_data: Dict[str, Any],
    customer_id: int,
    user_id: int,
    due_date: Optional[datetime],
    now: datetime,
    opportunity_id: Optional[int] = None,
) -> Milestone:
    """Create a new Milestone from MSX data."""
    return Milestone(
        msx_milestone_id=msx_data["id"],
        milestone_number=msx_data.get("number", ""),
        url=msx_data.get("url", ""),
        title=msx_data.get("name", ""),
        msx_status=msx_data.get("status", "Unknown"),
        msx_status_code=msx_data.get("status_code"),
        opportunity_name=msx_data.get("opportunity_name", ""),
        workload=msx_data.get("workload", ""),
        monthly_usage=msx_data.get("monthly_usage"),
        due_date=due_date,
        dollar_value=msx_data.get("dollar_value"),
        last_synced_at=now,
        customer_id=customer_id,
        user_id=user_id,
        opportunity_id=opportunity_id,
    )


def _upsert_opportunity(
    msx_data: Dict[str, Any],
    customer_id: int,
    user_id: int,
) -> Optional[Opportunity]:
    """
    Upsert an Opportunity record from milestone data.
    
    The milestone API returns the parent opportunity GUID and name.
    We create or update the Opportunity record so milestones can FK to it.
    
    Args:
        msx_data: Milestone dict from MSX API (contains msx_opportunity_id, opportunity_name).
        customer_id: The customer this opportunity belongs to.
        user_id: The user ID for new records.
        
    Returns:
        The Opportunity instance, or None if no opportunity GUID was provided.
    """
    msx_opp_id = msx_data.get("msx_opportunity_id")
    if not msx_opp_id:
        return None
    
    opp_name = msx_data.get("opportunity_name", "Unknown Opportunity")
    
    opportunity = Opportunity.query.filter_by(msx_opportunity_id=msx_opp_id).first()
    if opportunity:
        # Update name in case it changed
        opportunity.name = opp_name or opportunity.name
        opportunity.customer_id = customer_id
    else:
        opportunity = Opportunity(
            msx_opportunity_id=msx_opp_id,
            name=opp_name,
            customer_id=customer_id,
            user_id=user_id,
        )
        db.session.add(opportunity)
        # Flush to get the ID assigned so we can FK to it
        db.session.flush()
    
    return opportunity


def _parse_msx_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a date string from MSX OData response.
    
    MSX returns dates in ISO 8601 format like "2025-06-30T00:00:00Z".
    
    Args:
        date_str: Date string from MSX, or None.
        
    Returns:
        datetime object or None if parsing fails.
    """
    if not date_str:
        return None
    try:
        # Handle ISO 8601 format with or without Z suffix
        date_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(date_str.replace("+00:00", ""))
    except (ValueError, AttributeError):
        logger.warning(f"Could not parse MSX date: {date_str}")
        return None


def _update_team_memberships() -> None:
    """
    Update the on_my_team flag for all milestones based on MSX access teams.

    Makes one API call to get all milestone team memberships, then bulk-updates
    the on_my_team column. Milestones the user is on get True, all others get
    False. Failures are logged but don't block the sync.
    """
    try:
        result = get_my_milestone_team_ids()
        if not result.get("success"):
            logger.warning(
                f"Could not fetch team memberships: {result.get('error')}"
            )
            return

        my_ids = result["milestone_ids"]
        logger.info(f"Updating on_my_team for {len(my_ids)} milestones")

        # Bulk update: set all to False first, then True for matches
        Milestone.query.update({Milestone.on_my_team: False})

        if my_ids:
            Milestone.query.filter(
                db.func.lower(Milestone.msx_milestone_id).in_(my_ids)
            ).update({Milestone.on_my_team: True}, synchronize_session='fetch')

        db.session.commit()
    except Exception as e:
        logger.exception("Error updating team memberships")
        db.session.rollback()


def get_milestone_tracker_data() -> Dict[str, Any]:
    """
    Get milestone data formatted for the tracker page.
    
    Returns active milestones grouped by urgency, sorted by dollar value
    (largest first within each group).
    
    Returns:
        Dict with:
        - milestones: list of milestone dicts with customer/seller info
        - summary: dict with totals and counts
        - last_sync: datetime of most recent sync, or None
    """
    # Query active milestones with eager-loaded relationships
    milestones = (
        Milestone.query
        .filter(Milestone.msx_status.in_(ACTIVE_STATUSES))
        .options(
            db.joinedload(Milestone.customer).joinedload(Customer.seller),
            db.joinedload(Milestone.customer).joinedload(Customer.territory),
            db.joinedload(Milestone.opportunity),
        )
        .all()
    )
    
    # Build the data structure
    now = datetime.now(timezone.utc)
    tracker_items = []
    
    total_monthly_usage = 0
    past_due_count = 0
    this_week_count = 0
    
    for ms in milestones:
        urgency = ms.due_date_urgency
        if urgency == 'past_due':
            past_due_count += 1
        elif urgency == 'this_week':
            this_week_count += 1
        
        if ms.monthly_usage and ms.monthly_usage > 0:
            total_monthly_usage += ms.monthly_usage
        
        # Days until due
        days_until = None
        fiscal_quarter = ""
        fiscal_year = ""
        if ms.due_date:
            due = ms.due_date if ms.due_date.tzinfo else ms.due_date.replace(tzinfo=timezone.utc)
            days_until = (due - now).days
            # Microsoft fiscal year starts July 1
            # Q1 = Jul-Sep, Q2 = Oct-Dec, Q3 = Jan-Mar, Q4 = Apr-Jun
            month = ms.due_date.month
            year = ms.due_date.year
            if month >= 7:
                fy = year + 1
                q = 1 if month <= 9 else 2
            else:
                fy = year
                q = 3 if month <= 3 else 4
            fiscal_quarter = f"FY{fy % 100:02d} Q{q}"
            fiscal_year = f"FY{fy % 100:02d}"
        
        # Extract area prefix from workload (e.g., "Infra" from "Infra: Windows")
        workload_area = ""
        if ms.workload and ':' in ms.workload:
            workload_area = ms.workload.split(':', 1)[0].strip()
        elif ms.workload:
            workload_area = ms.workload.strip()
        
        tracker_items.append({
            "id": ms.id,
            "title": ms.display_text,
            "milestone_number": ms.milestone_number,
            "status": ms.msx_status,
            "status_sort": ms.status_sort_order,
            "opportunity_name": ms.opportunity_name,
            "workload": ms.workload,
            "workload_area": workload_area,
            "monthly_usage": ms.monthly_usage,
            "due_date": ms.due_date,
            "dollar_value": ms.dollar_value,
            "days_until_due": days_until,
            "fiscal_quarter": fiscal_quarter,
            "fiscal_year": fiscal_year,
            "urgency": urgency,
            "url": ms.url,
            "last_synced_at": ms.last_synced_at,
            "on_my_team": ms.on_my_team,
            "customer": {
                "id": ms.customer.id if ms.customer else None,
                "name": ms.customer.get_display_name() if ms.customer else "Unknown",
            } if ms.customer else None,
            "seller": {
                "id": ms.customer.seller.id,
                "name": ms.customer.seller.name,
            } if ms.customer and ms.customer.seller else None,
            "territory": {
                "id": ms.customer.territory.id,
                "name": ms.customer.territory.name,
            } if ms.customer and ms.customer.territory else None,
            "opportunity": {
                "id": ms.opportunity.id,
                "name": ms.opportunity.name,
            } if ms.opportunity else None,
        })
    
    # Default sort: largest monthly usage first
    tracker_items.sort(key=lambda x: -(x["monthly_usage"] or 0))
    
    # Get last sync time
    last_sync = (
        db.session.query(db.func.max(Milestone.last_synced_at))
        .filter(Milestone.last_synced_at.isnot(None))
        .scalar()
    )
    
    # Get unique sellers for filter dropdown
    seller_ids = set()
    sellers = []
    for item in tracker_items:
        if item["seller"] and item["seller"]["id"] not in seller_ids:
            seller_ids.add(item["seller"]["id"])
            sellers.append(item["seller"])
    sellers.sort(key=lambda s: s["name"])
    
    # Get unique workload areas for filter dropdown
    areas = sorted(set(
        item["workload_area"] for item in tracker_items
        if item["workload_area"]
    ))
    
    # Get unique fiscal quarters for filter dropdown, sorted chronologically
    quarters = sorted(set(
        item["fiscal_quarter"] for item in tracker_items
        if item["fiscal_quarter"]
    ))
    
    return {
        "milestones": tracker_items,
        "summary": {
            "total_count": len(tracker_items),
            "total_monthly_usage": total_monthly_usage,
            "past_due_count": past_due_count,
            "this_week_count": this_week_count,
        },
        "last_sync": last_sync,
        "sellers": sellers,
        "areas": areas,
        "quarters": quarters,
    }
