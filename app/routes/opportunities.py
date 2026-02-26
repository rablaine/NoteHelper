"""
Opportunity routes for NoteHelper.
Handles viewing opportunity details (fetched fresh from MSX) and posting comments.
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g

from app.models import db, Opportunity, Milestone
from app.services.msx_api import get_opportunity, add_opportunity_comment, build_opportunity_url

logger = logging.getLogger(__name__)

# Create blueprint
opportunities_bp = Blueprint('opportunities', __name__)


@opportunities_bp.route('/opportunity/<int:id>')
def opportunity_view(id: int):
    """
    View opportunity details.
    
    Loads the local Opportunity record for customer/milestone context,
    then fetches fresh details from MSX (comments, status, value, etc.).
    """
    opportunity = Opportunity.query.get_or_404(id)
    
    # Get local milestones linked to this opportunity
    milestones = Milestone.query.filter_by(
        opportunity_id=opportunity.id
    ).order_by(Milestone.msx_status, Milestone.title).all()
    
    # Fetch fresh opportunity data from MSX
    msx_data = None
    msx_error = None
    msx_result = get_opportunity(opportunity.msx_opportunity_id)
    if msx_result.get("success"):
        msx_data = msx_result["opportunity"]
    else:
        msx_error = msx_result.get("error", "Could not fetch from MSX")
    
    return render_template(
        'opportunity_view.html',
        opportunity=opportunity,
        milestones=milestones,
        msx_data=msx_data,
        msx_error=msx_error,
    )


@opportunities_bp.route('/opportunity/<int:id>/comment', methods=['POST'])
def opportunity_add_comment(id: int):
    """Post a new comment to an opportunity's MSX forecast comments."""
    opportunity = Opportunity.query.get_or_404(id)
    
    comment_text = request.form.get('comment', '').strip()
    if not comment_text:
        flash('Comment cannot be empty.', 'warning')
        return redirect(url_for('opportunities.opportunity_view', id=id))
    
    result = add_opportunity_comment(opportunity.msx_opportunity_id, comment_text)
    
    if result.get("success"):
        flash('Comment posted to MSX.', 'success')
    else:
        flash(f'Failed to post comment: {result.get("error", "Unknown error")}', 'danger')
    
    return redirect(url_for('opportunities.opportunity_view', id=id))


@opportunities_bp.route('/api/opportunity/<int:id>/comment', methods=['POST'])
def api_opportunity_add_comment(id: int):
    """API endpoint to post a comment (for AJAX usage)."""
    opportunity = Opportunity.query.get_or_404(id)
    
    data = request.get_json()
    if not data or not data.get('comment', '').strip():
        return jsonify({"success": False, "error": "Comment cannot be empty"}), 400
    
    result = add_opportunity_comment(
        opportunity.msx_opportunity_id,
        data['comment'].strip()
    )
    
    return jsonify(result)
