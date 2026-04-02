"""Shared tool registry for Copilot chat panel and MCP server.

Tools are registered via the @tool decorator. Each tool is a thin wrapper
over existing service/query code - never duplicate business logic here.

Consumers:
    - Chat endpoint (Phase 2): get_openai_tools() + execute_tool()
    - MCP server (Phase 5): get_mcp_tools() + execute_tool()
"""
from typing import Any

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOLS: list[dict] = []


def tool(name: str, description: str, parameters: dict):
    """Register a function as a Copilot/MCP tool.

    Args:
        name: Unique tool name (snake_case).
        description: One-line description for the LLM.
        parameters: JSON Schema object describing accepted parameters.
    """
    def decorator(func):
        TOOLS.append({
            'name': name,
            'description': description,
            'parameters': parameters,
            'handler': func,
        })
        return func
    return decorator


def get_openai_tools() -> list[dict]:
    """Convert registry to OpenAI function-calling format."""
    return [
        {
            'type': 'function',
            'function': {
                'name': t['name'],
                'description': t['description'],
                'parameters': t['parameters'],
            },
        }
        for t in TOOLS
    ]


def get_mcp_tools() -> list[dict]:
    """Convert registry to MCP tool format."""
    return [
        {
            'name': t['name'],
            'description': t['description'],
            'inputSchema': t['parameters'],
        }
        for t in TOOLS
    ]


def execute_tool(name: str, params: dict) -> Any:
    """Dispatch a tool call by name.

    Args:
        name: The tool name to invoke.
        params: Dict of parameters matching the tool's schema.

    Returns:
        The tool handler's return value (should be JSON-serializable).

    Raises:
        ValueError: If the tool name is not registered.
    """
    for t in TOOLS:
        if t['name'] == name:
            return t['handler'](**params)
    raise ValueError(f'Unknown tool: {name}')


# ============================================================================
# Entity tools
# ============================================================================

# -- Customers ---------------------------------------------------------------

@tool(
    'search_customers',
    'Search customers by name, territory, seller, or vertical.',
    {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'Name or partial name to search for.',
            },
            'seller_id': {
                'type': 'integer',
                'description': 'Filter to a specific seller.',
            },
            'territory_id': {
                'type': 'integer',
                'description': 'Filter to a specific territory.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 20).',
            },
        },
    },
)
def search_customers(
    query: str = '',
    seller_id: int | None = None,
    territory_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search customers by name with optional seller/territory filters."""
    from app.models import Customer

    q = Customer.query
    if query:
        q = q.filter(Customer.name.ilike(f'%{query}%'))
    if seller_id:
        q = q.filter(Customer.seller_id == seller_id)
    if territory_id:
        q = q.filter(Customer.territory_id == territory_id)
    customers = q.order_by(Customer.name).limit(limit).all()
    return [
        {
            'id': c.id,
            'name': c.name,
            'nickname': c.nickname,
            'tpid': c.tpid,
            'seller': c.seller.name if c.seller else None,
            'territory': c.territory.name if c.territory else None,
        }
        for c in customers
    ]


@tool(
    'get_customer_summary',
    'Get an activity summary for a customer including engagements, '
    'milestones, recent notes, and contacts.',
    {
        'type': 'object',
        'properties': {
            'customer_id': {
                'type': 'integer',
                'description': 'Customer ID.',
            },
        },
        'required': ['customer_id'],
    },
)
def get_customer_summary(customer_id: int) -> dict:
    """Return a summary of a customer's activity."""
    from app.models import db, Customer, Engagement, Milestone, Note

    customer = db.session.get(Customer, customer_id)
    if not customer:
        return {'error': f'Customer {customer_id} not found.'}

    engagements = (
        Engagement.query
        .filter_by(customer_id=customer_id)
        .order_by(Engagement.updated_at.desc())
        .all()
    )
    milestones = (
        Milestone.query
        .filter_by(customer_id=customer_id)
        .order_by(Milestone.due_date.desc().nullslast())
        .limit(10)
        .all()
    )
    recent_notes = (
        Note.query
        .filter_by(customer_id=customer_id)
        .order_by(Note.call_date.desc())
        .limit(5)
        .all()
    )

    return {
        'id': customer.id,
        'name': customer.name,
        'nickname': customer.nickname,
        'seller': customer.seller.name if customer.seller else None,
        'territory': customer.territory.name if customer.territory else None,
        'engagements': [
            {
                'id': e.id,
                'title': e.title,
                'status': e.status,
                'updated_at': e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in engagements
        ],
        'milestones': [
            {
                'id': m.id,
                'title': m.display_text,
                'status': m.msx_status,
                'due_date': m.due_date.strftime('%Y-%m-%d') if m.due_date else None,
                'on_my_team': m.on_my_team,
            }
            for m in milestones
        ],
        'recent_notes': [
            {
                'id': n.id,
                'call_date': n.call_date.strftime('%Y-%m-%d') if n.call_date else None,
                'snippet': (n.content or '')[:200],
            }
            for n in recent_notes
        ],
    }


# -- Notes -------------------------------------------------------------------

@tool(
    'search_notes',
    'Search call notes by keyword, customer, seller, topic, or date range.',
    {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'Full-text keyword search.',
            },
            'customer_id': {
                'type': 'integer',
                'description': 'Filter to a specific customer.',
            },
            'topic_id': {
                'type': 'integer',
                'description': 'Filter to notes tagged with this topic.',
            },
            'days': {
                'type': 'integer',
                'description': 'Limit to notes from the last N days.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 20).',
            },
        },
    },
)
def search_notes(
    query: str = '',
    customer_id: int | None = None,
    topic_id: int | None = None,
    days: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search call notes with optional filters."""
    from datetime import datetime, timedelta, timezone
    from app.models import Note

    q = Note.query
    if query:
        q = q.filter(Note.content.ilike(f'%{query}%'))
    if customer_id:
        q = q.filter(Note.customer_id == customer_id)
    if topic_id:
        q = q.filter(Note.topics.any(id=topic_id))
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.filter(Note.call_date >= cutoff)
    notes = q.order_by(Note.call_date.desc()).limit(limit).all()
    return [
        {
            'id': n.id,
            'customer': n.customer.name if n.customer else None,
            'call_date': n.call_date.strftime('%Y-%m-%d') if n.call_date else None,
            'snippet': (n.content or '')[:200],
            'topics': [t.name for t in n.topics],
        }
        for n in notes
    ]


# -- Engagements ------------------------------------------------------------

@tool(
    'get_engagement_details',
    'Get engagement info including status, story fields, action items, and linked notes.',
    {
        'type': 'object',
        'properties': {
            'engagement_id': {
                'type': 'integer',
                'description': 'Engagement ID.',
            },
        },
        'required': ['engagement_id'],
    },
)
def get_engagement_details(engagement_id: int) -> dict:
    """Return details for a single engagement."""
    from app.models import db, Engagement

    eng = db.session.get(Engagement, engagement_id)
    if not eng:
        return {'error': f'Engagement {engagement_id} not found.'}

    return {
        'id': eng.id,
        'title': eng.title,
        'status': eng.status,
        'customer': eng.customer.name if eng.customer else None,
        'customer_id': eng.customer_id,
        'scenario': eng.scenario,
        'problem_statement': eng.problem_statement,
        'desired_outcome': eng.desired_outcome,
        'proposed_solution': eng.proposed_solution,
        'action_items': [
            {
                'id': ai.id,
                'description': ai.description,
                'status': ai.status,
                'due_date': ai.due_date.strftime('%Y-%m-%d') if ai.due_date else None,
            }
            for ai in eng.action_items
        ],
        'note_count': len(eng.notes),
    }


# -- Milestones --------------------------------------------------------------

@tool(
    'get_milestone_status',
    'Get milestone details or list milestones filtered by status, customer, or seller.',
    {
        'type': 'object',
        'properties': {
            'milestone_id': {
                'type': 'integer',
                'description': 'Get a specific milestone by ID.',
            },
            'customer_id': {
                'type': 'integer',
                'description': 'Filter milestones to a customer.',
            },
            'status': {
                'type': 'string',
                'description': 'Filter by MSX status (On Track, At Risk, Blocked, etc.).',
            },
            'on_my_team': {
                'type': 'boolean',
                'description': 'Filter to milestones where user is on the team.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 20).',
            },
        },
    },
)
def get_milestone_status(
    milestone_id: int | None = None,
    customer_id: int | None = None,
    status: str | None = None,
    on_my_team: bool | None = None,
    limit: int = 20,
) -> dict | list[dict]:
    """Get milestone details or search milestones."""
    from app.models import db, Milestone

    if milestone_id:
        ms = db.session.get(Milestone, milestone_id)
        if not ms:
            return {'error': f'Milestone {milestone_id} not found.'}
        return {
            'id': ms.id,
            'title': ms.display_text,
            'status': ms.msx_status,
            'customer': ms.customer.name if ms.customer else None,
            'due_date': ms.due_date.strftime('%Y-%m-%d') if ms.due_date else None,
            'monthly_usage': ms.monthly_usage,
            'on_my_team': ms.on_my_team,
            'workload': ms.workload,
            'url': ms.url,
        }

    q = Milestone.query
    if customer_id:
        q = q.filter(Milestone.customer_id == customer_id)
    if status:
        q = q.filter(Milestone.msx_status == status)
    if on_my_team is not None:
        q = q.filter(Milestone.on_my_team == on_my_team)
    milestones = q.order_by(Milestone.due_date.asc().nullslast()).limit(limit).all()
    return [
        {
            'id': m.id,
            'title': m.display_text,
            'status': m.msx_status,
            'customer': m.customer.name if m.customer else None,
            'due_date': m.due_date.strftime('%Y-%m-%d') if m.due_date else None,
            'monthly_usage': m.monthly_usage,
            'on_my_team': m.on_my_team,
        }
        for m in milestones
    ]


# -- Sellers -----------------------------------------------------------------

@tool(
    'get_seller_workload',
    "Get a seller's customers, open engagement count, and milestone summary.",
    {
        'type': 'object',
        'properties': {
            'seller_id': {
                'type': 'integer',
                'description': 'Seller ID.',
            },
        },
        'required': ['seller_id'],
    },
)
def get_seller_workload(seller_id: int) -> dict:
    """Return workload summary for a seller."""
    from app.models import db, Seller, Engagement, Milestone

    seller = db.session.get(Seller, seller_id)
    if not seller:
        return {'error': f'Seller {seller_id} not found.'}

    customers = seller.customers
    customer_ids = [c.id for c in customers]

    open_engagements = (
        Engagement.query
        .filter(
            Engagement.customer_id.in_(customer_ids),
            Engagement.status == 'Active',
        )
        .count()
    ) if customer_ids else 0

    active_milestones = (
        Milestone.query
        .filter(
            Milestone.customer_id.in_(customer_ids),
            Milestone.on_my_team == True,
        )
        .count()
    ) if customer_ids else 0

    return {
        'id': seller.id,
        'name': seller.name,
        'seller_type': seller.seller_type,
        'customer_count': len(customers),
        'open_engagements': open_engagements,
        'active_milestones': active_milestones,
        'territories': [t.name for t in seller.territories],
    }


# -- Opportunities -----------------------------------------------------------

@tool(
    'get_opportunity_details',
    'Get opportunity details including linked milestones and engagements.',
    {
        'type': 'object',
        'properties': {
            'opportunity_id': {
                'type': 'integer',
                'description': 'Opportunity ID.',
            },
        },
        'required': ['opportunity_id'],
    },
)
def get_opportunity_details(opportunity_id: int) -> dict:
    """Return details for a single opportunity."""
    from app.models import db, Opportunity

    opp = db.session.get(Opportunity, opportunity_id)
    if not opp:
        return {'error': f'Opportunity {opportunity_id} not found.'}

    return {
        'id': opp.id,
        'name': opp.name,
        'customer': opp.customer.name if opp.customer else None,
        'msx_url': opp.msx_url,
        'milestones': [
            {'id': m.id, 'title': m.display_text, 'status': m.msx_status}
            for m in opp.milestones
        ],
    }


# -- Partners ----------------------------------------------------------------

@tool(
    'search_partners',
    'Search partner organizations by name or specialty.',
    {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'Partner name search.',
            },
            'specialty': {
                'type': 'string',
                'description': 'Filter to partners with this specialty.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 20).',
            },
        },
    },
)
def search_partners(
    query: str = '',
    specialty: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search partners by name or specialty."""
    from app.models import Partner, Specialty

    q = Partner.query
    if query:
        q = q.filter(Partner.name.ilike(f'%{query}%'))
    if specialty:
        q = q.filter(Partner.specialties.any(Specialty.name.ilike(f'%{specialty}%')))
    partners = q.order_by(Partner.name).limit(limit).all()
    return [
        {
            'id': p.id,
            'name': p.name,
            'specialties': [s.name for s in p.specialties],
        }
        for p in partners
    ]


# -- Action Items ------------------------------------------------------------

@tool(
    'list_action_items',
    'List open action items, optionally filtered by engagement or project.',
    {
        'type': 'object',
        'properties': {
            'engagement_id': {
                'type': 'integer',
                'description': 'Filter to a specific engagement.',
            },
            'status': {
                'type': 'string',
                'description': 'Filter by status (open, completed, cancelled).',
            },
            'overdue_only': {
                'type': 'boolean',
                'description': 'Only return overdue items.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 30).',
            },
        },
    },
)
def list_action_items(
    engagement_id: int | None = None,
    status: str | None = None,
    overdue_only: bool = False,
    limit: int = 30,
) -> list[dict]:
    """List action items with optional filters."""
    from datetime import date
    from app.models import ActionItem

    q = ActionItem.query
    if engagement_id:
        q = q.filter(ActionItem.engagement_id == engagement_id)
    if status:
        q = q.filter(ActionItem.status == status)
    if overdue_only:
        q = q.filter(
            ActionItem.status == 'open',
            ActionItem.due_date < date.today(),
        )
    items = q.order_by(ActionItem.due_date.asc().nullslast()).limit(limit).all()
    return [
        {
            'id': ai.id,
            'description': ai.description,
            'status': ai.status,
            'priority': ai.priority,
            'due_date': ai.due_date.strftime('%Y-%m-%d') if ai.due_date else None,
            'engagement': ai.engagement.title if ai.engagement else None,
            'customer': (
                ai.engagement.customer.name
                if ai.engagement and ai.engagement.customer
                else None
            ),
        }
        for ai in items
    ]


# ============================================================================
# Report tools
# ============================================================================

@tool(
    'report_hygiene',
    'Get data hygiene gaps: engagements missing milestones and milestones missing engagements.',
    {
        'type': 'object',
        'properties': {
            'seller_id': {
                'type': 'integer',
                'description': 'Scope to a specific seller.',
            },
        },
    },
)
def report_hygiene(seller_id: int | None = None) -> dict:
    """Return hygiene report data."""
    from app.models import Engagement, Milestone

    eng_q = (
        Engagement.query
        .filter(Engagement.status == 'Active')
        .filter(~Engagement.milestones.any())
    )
    ms_q = (
        Milestone.query
        .filter(Milestone.on_my_team == True)
        .filter(~Milestone.engagements.any())
    )
    if seller_id:
        from app.models import Customer
        cust_ids = [
            c.id for c in Customer.query.filter_by(seller_id=seller_id).all()
        ]
        eng_q = eng_q.filter(Engagement.customer_id.in_(cust_ids))
        ms_q = ms_q.filter(Milestone.customer_id.in_(cust_ids))

    return {
        'engagements_without_milestones': [
            {
                'id': e.id,
                'title': e.title,
                'customer': e.customer.name if e.customer else None,
            }
            for e in eng_q.all()
        ],
        'milestones_without_engagements': [
            {
                'id': m.id,
                'title': m.display_text,
                'customer': m.customer.name if m.customer else None,
                'status': m.msx_status,
            }
            for m in ms_q.all()
        ],
    }


@tool(
    'report_workload',
    'Get workload coverage - customers grouped by topic/workload with counts.',
    {
        'type': 'object',
        'properties': {
            'seller_id': {
                'type': 'integer',
                'description': 'Scope to a seller.',
            },
        },
    },
)
def report_workload(seller_id: int | None = None) -> dict:
    """Return workload summary counts."""
    from app.models import Customer, Engagement, Milestone

    cust_q = Customer.query
    if seller_id:
        cust_q = cust_q.filter_by(seller_id=seller_id)
    customers = cust_q.all()

    return {
        'customer_count': len(customers),
        'customers': [
            {
                'id': c.id,
                'name': c.name,
                'engagement_count': Engagement.query.filter_by(
                    customer_id=c.id, status='Active'
                ).count(),
                'milestone_count': Milestone.query.filter(
                    Milestone.customer_id == c.id,
                    Milestone.on_my_team == True,
                ).count(),
            }
            for c in customers[:50]  # Cap to avoid huge responses
        ],
    }


@tool(
    'report_whats_new',
    'Get milestones created or updated in the last N days.',
    {
        'type': 'object',
        'properties': {
            'days': {
                'type': 'integer',
                'description': 'Lookback window in days (default 14, max 90).',
            },
        },
    },
)
def report_whats_new(days: int = 14) -> dict:
    """Return recently created/updated milestones."""
    from datetime import datetime, timedelta, timezone
    from app.models import db, Milestone

    days = max(1, min(days, 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    created = (
        Milestone.query
        .filter(
            db.or_(
                Milestone.msx_created_on >= cutoff,
                db.and_(
                    Milestone.msx_created_on.is_(None),
                    Milestone.created_at >= cutoff,
                ),
            )
        )
        .order_by(Milestone.created_at.desc())
        .limit(50)
        .all()
    )
    updated = (
        Milestone.query
        .filter(
            Milestone.msx_modified_on >= cutoff,
            db.or_(
                Milestone.msx_created_on < cutoff,
                Milestone.msx_created_on.is_(None),
            ),
        )
        .order_by(Milestone.msx_modified_on.desc())
        .limit(50)
        .all()
    )

    def _ms_dict(m):
        return {
            'id': m.id,
            'title': m.display_text,
            'customer': m.customer.name if m.customer else None,
            'status': m.msx_status,
            'on_my_team': m.on_my_team,
        }

    return {
        'days': days,
        'created': [_ms_dict(m) for m in created],
        'updated': [_ms_dict(m) for m in updated],
    }


@tool(
    'report_revenue_alerts',
    'Get revenue alerts - customers with declining revenue, dips, or expansion opportunities.',
    {
        'type': 'object',
        'properties': {
            'category': {
                'type': 'string',
                'description': 'Filter by category (CHURN_RISK, RECENT_DIP, '
                'EXPANSION_OPPORTUNITY, VOLATILE).',
            },
            'seller_name': {
                'type': 'string',
                'description': 'Filter to a specific seller by name.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Max results (default 20).',
            },
        },
    },
)
def report_revenue_alerts(
    category: str | None = None,
    seller_name: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return revenue analysis alerts."""
    from app.models import RevenueAnalysis

    q = RevenueAnalysis.query.filter(
        RevenueAnalysis.review_status.in_(['new', 'to_be_reviewed'])
    )
    if category:
        q = q.filter(RevenueAnalysis.category == category)
    if seller_name:
        q = q.filter(RevenueAnalysis.seller_name == seller_name)
    alerts = (
        q.order_by(RevenueAnalysis.priority_score.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            'id': a.id,
            'customer_name': a.customer_name,
            'bucket': a.bucket,
            'category': a.category,
            'priority_score': a.priority_score,
            'dollars_at_risk': a.dollars_at_risk,
            'dollars_opportunity': a.dollars_opportunity,
            'engagement_rationale': a.engagement_rationale,
        }
        for a in alerts
    ]


@tool(
    'report_whitespace',
    'Get whitespace analysis - which customers are missing coverage in which '
    'technology buckets.',
    {
        'type': 'object',
        'properties': {
            'customer_id': {
                'type': 'integer',
                'description': 'Check whitespace for a specific customer.',
            },
            'bucket': {
                'type': 'string',
                'description': 'Check which customers lack coverage in this bucket.',
            },
        },
    },
)
def report_whitespace(
    customer_id: int | None = None,
    bucket: str | None = None,
) -> dict:
    """Return whitespace gaps."""
    from app.models import CustomerRevenueData

    if customer_id:
        rows = (
            CustomerRevenueData.query
            .filter_by(customer_id=customer_id)
            .all()
        )
        buckets_with_spend = {r.bucket for r in rows if r.latest_month and r.latest_month > 0}
        return {
            'customer_id': customer_id,
            'buckets_with_spend': sorted(buckets_with_spend),
        }

    if bucket:
        customers_with = (
            CustomerRevenueData.query
            .filter_by(bucket=bucket)
            .filter(CustomerRevenueData.latest_month > 0)
            .all()
        )
        return {
            'bucket': bucket,
            'customers_with_spend': len(customers_with),
        }

    return {'error': 'Provide customer_id or bucket to query whitespace.'}
