"""
Routes for milestone management.
Milestones are URLs from the MSX sales platform that can be linked to call logs.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from app.models import db, Milestone, CallLog

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
