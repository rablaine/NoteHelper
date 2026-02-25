"""
Routes for milestone management and milestone tracker.
Milestones are URLs from the MSX sales platform that can be linked to call logs.
The Milestone Tracker provides visibility into all active (uncommitted) milestones
across customers, sorted by dollar value and due date urgency.
"""
import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, jsonify, Response, stream_with_context,
)
from app.models import db, Milestone, CallLog

logger = logging.getLogger(__name__)

bp = Blueprint('milestones', __name__)


@bp.route('/milestones')
def milestones_list():
    """List all milestones."""
    milestones = Milestone.query.order_by(Milestone.created_at.desc()).all()
    return render_template('milestones_list.html', milestones=milestones)


@bp.route('/milestone/new', methods=['GET', 'POST'])
def milestone_create():
    """Create a new milestone."""
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        title = request.form.get('title', '').strip() or None
        
        if not url:
            flash('URL is required', 'danger')
            return render_template('milestone_form.html', milestone=None)
        
        # Check for duplicate URL
        existing = Milestone.query.filter_by(url=url).first()
        if existing:
            flash('A milestone with this URL already exists', 'danger')
            return render_template('milestone_form.html', milestone=None)
        
        milestone = Milestone(
            url=url,
            title=title,
            user_id=g.user.id
        )
        db.session.add(milestone)
        db.session.commit()
        
        flash('Milestone created successfully', 'success')
        return redirect(url_for('milestones.milestone_view', id=milestone.id))
    
    return render_template('milestone_form.html', milestone=None)


@bp.route('/milestone/<int:id>')
def milestone_view(id):
    """View a milestone and its associated call logs."""
    milestone = Milestone.query.get_or_404(id)
    return render_template('milestone_view.html', milestone=milestone)


@bp.route('/milestone/<int:id>/edit', methods=['GET', 'POST'])
def milestone_edit(id):
    """Edit a milestone."""
    milestone = Milestone.query.get_or_404(id)
    
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        title = request.form.get('title', '').strip() or None
        
        if not url:
            flash('URL is required', 'danger')
            return render_template('milestone_form.html', milestone=milestone)
        
        # Check for duplicate URL (excluding current milestone)
        existing = Milestone.query.filter(
            Milestone.url == url,
            Milestone.id != milestone.id
        ).first()
        if existing:
            flash('A milestone with this URL already exists', 'danger')
            return render_template('milestone_form.html', milestone=milestone)
        
        milestone.url = url
        milestone.title = title
        db.session.commit()
        
        flash('Milestone updated successfully', 'success')
        return redirect(url_for('milestones.milestone_view', id=milestone.id))
    
    return render_template('milestone_form.html', milestone=milestone)


@bp.route('/milestone/<int:id>/delete', methods=['POST'])
def milestone_delete(id):
    """Delete a milestone."""
    milestone = Milestone.query.get_or_404(id)
    
    db.session.delete(milestone)
    db.session.commit()
    
    flash('Milestone deleted successfully', 'success')
    return redirect(url_for('milestones.milestones_list'))


@bp.route('/api/milestones/find-or-create', methods=['POST'])
def api_find_or_create_milestone():
    """Find an existing milestone by URL or create a new one.
    
    Used by the call log form when associating a milestone URL.
    """
    data = request.get_json()
    if not data or not data.get('url'):
        return jsonify({'error': 'URL is required'}), 400
    
    url = data['url'].strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Try to find existing milestone
    milestone = Milestone.query.filter_by(url=url).first()
    
    if not milestone:
        # Create new milestone
        milestone = Milestone(
            url=url,
            title=None,
            user_id=g.user.id
        )
        db.session.add(milestone)
        db.session.commit()
    
    return jsonify({
        'id': milestone.id,
        'url': milestone.url,
        'title': milestone.title,
        'display_text': milestone.display_text,
        'created': milestone is not None
    })


# =============================================================================
# Milestone Tracker
# =============================================================================

@bp.route('/milestone-tracker')
def milestone_tracker():
    """
    Milestone Tracker page.
    
    Shows all active (uncommitted) milestones across customers, sorted by
    dollar value and grouped by due date urgency. Provides a sync button
    to pull fresh data from MSX.
    """
    from app.services.milestone_sync import get_milestone_tracker_data
    
    tracker_data = get_milestone_tracker_data()
    return render_template(
        'milestone_tracker.html',
        milestones=tracker_data["milestones"],
        summary=tracker_data["summary"],
        last_sync=tracker_data["last_sync"],
        sellers=tracker_data["sellers"],
        areas=tracker_data["areas"],
    )


@bp.route('/api/milestone-tracker/sync', methods=['POST'])
def api_sync_milestones():
    """
    Trigger a milestone sync from MSX with Server-Sent Events progress.

    Streams real-time progress events as each customer is synced.
    Falls back to JSON response if Accept header doesn't include event-stream.
    """
    from app.services.milestone_sync import (
        sync_all_customer_milestones,
        sync_all_customer_milestones_stream,
    )

    user_id = g.user.id

    # SSE streaming path
    if 'text/event-stream' in request.headers.get('Accept', ''):
        def generate():
            yield from sync_all_customer_milestones_stream(user_id)

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )

    # JSON fallback for non-SSE clients
    try:
        results = sync_all_customer_milestones(user_id=user_id)
        status_code = 200 if results["success"] else 207
        return jsonify(results), status_code
    except Exception as e:
        logger.exception("Milestone sync failed")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route('/api/milestone-tracker/sync-customer/<int:customer_id>', methods=['POST'])
def api_sync_customer_milestones(customer_id):
    """
    Sync milestones from MSX for a single customer.
    
    Args:
        customer_id: The customer ID to sync.
        
    Returns:
        JSON with sync results for the single customer.
    """
    from app.models import Customer
    from app.services.milestone_sync import sync_customer_milestones
    
    customer = Customer.query.get_or_404(customer_id)
    
    if not customer.tpid_url:
        return jsonify({
            "success": False,
            "error": "Customer has no MSX account link (tpid_url).",
        }), 400
    
    try:
        result = sync_customer_milestones(customer, user_id=g.user.id)
        return jsonify(result)
    except Exception as e:
        logger.exception(f"Milestone sync failed for customer {customer_id}")
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500
