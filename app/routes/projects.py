"""
Project routes for Sales Buddy.
Handles internal project CRUD - non-customer work like training, copilot saved tasks, etc.
"""
import logging
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.models import db, Project, ActionItem, Note, notes_projects

logger = logging.getLogger(__name__)

projects_bp = Blueprint('projects', __name__)


@projects_bp.route('/project/new', methods=['GET', 'POST'])
def project_create():
    """Create a new internal project."""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        project_type = request.form.get('project_type', 'general').strip()
        due_date_str = request.form.get('due_date', '').strip()

        if not title:
            flash('Project title is required.', 'danger')
            return redirect(url_for('projects.project_create'))

        project = Project(
            title=title,
            description=description or None,
            project_type=project_type,
        )
        if due_date_str:
            try:
                project.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        db.session.add(project)
        db.session.commit()
        flash(f'Project "{title}" created!', 'success')
        return redirect(url_for('projects.project_view', id=project.id))

    return render_template('project_form.html', project=None,
                         project_types=Project.BUILT_IN_TYPES)


@projects_bp.route('/project/<int:id>')
def project_view(id):
    """View project details with notes and action items."""
    project = Project.query.get_or_404(id)
    return render_template('project_view.html', project=project)


@projects_bp.route('/project/<int:id>/edit', methods=['GET', 'POST'])
def project_edit(id):
    """Edit an existing project."""
    project = Project.query.get_or_404(id)

    if request.method == 'POST':
        project.title = request.form.get('title', '').strip() or project.title
        project.description = request.form.get('description', '').strip() or None
        project.status = request.form.get('status', project.status)
        project.project_type = request.form.get('project_type', project.project_type)
        due_date_str = request.form.get('due_date', '').strip()
        if due_date_str:
            try:
                project.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        else:
            project.due_date = None

        db.session.commit()
        flash('Project updated.', 'success')
        return redirect(url_for('projects.project_view', id=project.id))

    return render_template('project_form.html', project=project,
                         project_types=Project.BUILT_IN_TYPES)


@projects_bp.route('/project/<int:id>/delete', methods=['POST'])
def project_delete(id):
    """Delete a project."""
    project = Project.query.get_or_404(id)
    title = project.title
    db.session.delete(project)
    db.session.commit()
    flash(f'Project "{title}" deleted.', 'success')
    return redirect(url_for('engagements.engagements_hub'))


@projects_bp.route('/api/project/<int:id>/action-item', methods=['POST'])
def project_add_action_item(id):
    """Add an action item to a project."""
    project = Project.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify(success=False, error='Title is required'), 400

    item = ActionItem(
        project_id=project.id,
        title=title,
        description=(data.get('description') or '').strip() or None,
        source='project',
        status='open',
        priority=data.get('priority', 'normal'),
    )
    due_str = (data.get('due_date') or '').strip()
    if due_str:
        try:
            item.due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    db.session.add(item)
    db.session.commit()
    return jsonify(success=True, id=item.id)
