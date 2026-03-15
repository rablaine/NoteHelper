"""
Note sharing service — serialization and import for shared notes.

Handles:
- Serializing a note (with customer, seller, territory, milestone, topics,
  partners) to JSON for sharing via Socket.IO
- Importing a received note into the local database, creating any missing
  customer/seller/territory/milestone/topic records as needed
"""
import logging
from datetime import datetime

from app.models import (
    db, Note, Customer, Seller, Territory, Milestone, Topic, Partner,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization — sender side
# ---------------------------------------------------------------------------

def serialize_note(note: Note) -> dict:
    """Serialize a note and all context needed for the recipient to import it.

    Includes customer (with TPID, seller, territory), topics, milestone
    (if MSX-sourced), and linked partner names.
    """
    data = {
        "content": note.content,
        "call_date": note.call_date.isoformat() if note.call_date else None,
    }

    # Customer context (required for import — recipient matches by TPID)
    if note.customer:
        c = note.customer
        customer_data = {
            "name": c.name,
            "tpid": c.tpid,
            "tpid_url": c.tpid_url,
            "website": c.website,
            "favicon_b64": c.favicon_b64,
        }
        # Seller info (from customer relationship)
        if c.seller:
            customer_data["seller_name"] = c.seller.name
            customer_data["seller_alias"] = c.seller.alias
            customer_data["seller_type"] = c.seller.seller_type
        # Territory info (from customer relationship)
        if c.territory:
            customer_data["territory_name"] = c.territory.name

        data["customer"] = customer_data

    # Topics
    if note.topics:
        data["topics"] = [t.name for t in note.topics]

    # Milestone — only include MSX-sourced milestones (have msx_milestone_id)
    if note.milestones:
        for ms in note.milestones:
            if ms.msx_milestone_id:
                data["milestone"] = {
                    "msx_milestone_id": ms.msx_milestone_id,
                    "milestone_number": ms.milestone_number,
                    "url": ms.url,
                    "title": ms.title,
                    "msx_status": ms.msx_status,
                    "due_date": ms.due_date.isoformat() if ms.due_date else None,
                    "dollar_value": ms.dollar_value,
                    "workload": ms.workload,
                }
                break  # Only include the first MSX-sourced milestone

    # Partner names — recipient will try to match by name
    if note.partners:
        data["partners"] = [p.name for p in note.partners]

    return data


# ---------------------------------------------------------------------------
# Import — recipient side
# ---------------------------------------------------------------------------

def import_shared_note(note_data: dict, sender_name: str) -> dict:
    """Import a shared note into the local database.

    Creates customer/seller/territory/milestone/topics if they don't exist.
    Returns a result dict with the action taken.

    Args:
        note_data: Serialized note dict from serialize_note()
        sender_name: Display name of the person who shared the note
    """
    content = note_data.get("content")
    if not content:
        return {"success": False, "error": "Note has no content"}

    call_date_str = note_data.get("call_date")
    call_date = datetime.fromisoformat(call_date_str) if call_date_str else datetime.now()

    customer_data = note_data.get("customer")
    customer = None
    created = []  # Track what entities were created

    if customer_data and customer_data.get("tpid"):
        customer, customer_created = _find_or_create_customer(customer_data)
        created.extend(customer_created)

    # Create the note
    note = Note(
        customer_id=customer.id if customer else None,
        content=content,
        call_date=call_date,
    )
    db.session.add(note)

    # Link topics (create if needed)
    for topic_name in note_data.get("topics", []):
        topic = _find_or_create_topic(topic_name)
        note.topics.append(topic)

    # Link milestone (create if needed, MSX-sourced only)
    milestone_data = note_data.get("milestone")
    if milestone_data and milestone_data.get("msx_milestone_id"):
        milestone = _find_or_create_milestone(milestone_data, customer)
        note.milestones.append(milestone)

    # Link partners by name (match only, don't create)
    for partner_name in note_data.get("partners", []):
        partner = Partner.query.filter(
            db.func.lower(Partner.name) == partner_name.lower()
        ).first()
        if partner:
            note.partners.append(partner)

    db.session.commit()
    logger.info(f"Imported shared note from {sender_name}"
                f" (customer={customer.name if customer else 'General'})")

    return {
        "success": True,
        "customer_name": customer.name if customer else None,
        "note_id": note.id,
        "created": created,
    }


def _find_or_create_customer(customer_data: dict) -> tuple[Customer, list[str]]:
    """Find a customer by TPID, or create with full context if not found.

    Returns (customer, created_list) where created_list tracks new entities.
    """
    tpid = customer_data["tpid"]
    customer = Customer.query.filter_by(tpid=tpid).first()
    if customer:
        return customer, []

    created = []

    # Need to create — first ensure territory and seller exist
    territory = None
    territory_name = customer_data.get("territory_name")
    if territory_name:
        territory = Territory.query.filter(
            db.func.lower(Territory.name) == territory_name.lower()
        ).first()
        if not territory:
            territory = Territory(name=territory_name)
            db.session.add(territory)
            db.session.flush()
            created.append(f"territory: {territory_name}")

    seller = None
    seller_name = customer_data.get("seller_name")
    if seller_name:
        # Match by alias first (more specific), then by name
        seller_alias = customer_data.get("seller_alias")
        if seller_alias:
            seller = Seller.query.filter(
                db.func.lower(Seller.alias) == seller_alias.lower()
            ).first()
        if not seller:
            seller = Seller.query.filter(
                db.func.lower(Seller.name) == seller_name.lower()
            ).first()
        if not seller:
            seller = Seller(
                name=seller_name,
                alias=seller_alias,
                seller_type=customer_data.get("seller_type", "Growth"),
            )
            db.session.add(seller)
            db.session.flush()
            created.append(f"seller: {seller_name}")
        # Link seller to territory via M:M
        if territory and territory not in seller.territories:
            seller.territories.append(territory)

    customer = Customer(
        name=customer_data["name"],
        tpid=tpid,
        tpid_url=customer_data.get("tpid_url"),
        website=customer_data.get("website"),
        favicon_b64=customer_data.get("favicon_b64"),
        territory_id=territory.id if territory else None,
        seller_id=seller.id if seller else None,
    )
    db.session.add(customer)
    db.session.flush()
    created.append(f"customer: {customer_data['name']}")
    logger.info(f"Created customer '{customer.name}' (TPID {tpid}) from shared note")
    return customer, created


def _find_or_create_topic(name: str) -> Topic:
    """Find a topic by name (case-insensitive) or create it."""
    topic = Topic.query.filter(
        db.func.lower(Topic.name) == name.lower()
    ).first()
    if not topic:
        topic = Topic(name=name)
        db.session.add(topic)
        db.session.flush()
    return topic


def _find_or_create_milestone(milestone_data: dict, customer: Customer | None) -> Milestone:
    """Find a milestone by MSX ID or create it."""
    msx_id = milestone_data["msx_milestone_id"]
    milestone = Milestone.query.filter_by(msx_milestone_id=msx_id).first()
    if milestone:
        return milestone

    due_date = None
    if milestone_data.get("due_date"):
        try:
            due_date = datetime.fromisoformat(milestone_data["due_date"])
        except (ValueError, TypeError):
            pass

    milestone = Milestone(
        msx_milestone_id=msx_id,
        milestone_number=milestone_data.get("milestone_number"),
        url=milestone_data.get("url", ""),
        title=milestone_data.get("title"),
        msx_status=milestone_data.get("msx_status"),
        due_date=due_date,
        dollar_value=milestone_data.get("dollar_value"),
        workload=milestone_data.get("workload"),
        customer_id=customer.id if customer else None,
    )
    db.session.add(milestone)
    db.session.flush()
    logger.info(f"Created milestone '{milestone.display_text}' from shared note")
    return milestone
