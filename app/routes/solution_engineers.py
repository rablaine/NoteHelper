"""
Solution Engineer routes for NoteHelper.
Handles solution engineer listing, viewing, and editing.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.models import db, SolutionEngineer, POD

# Create blueprint
solution_engineers_bp = Blueprint('solution_engineers', __name__)


@solution_engineers_bp.route('/solution-engineers')
def solution_engineers_list():
    """List all solution engineers."""
    ses = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).order_by(SolutionEngineer.name).all()
    return render_template('solution_engineers_list.html', solution_engineers=ses)


@solution_engineers_bp.route('/solution-engineer/<int:id>')
def solution_engineer_view(id):
    """View solution engineer details."""
    se = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).filter_by(id=id).first_or_404()
    
    # Sort PODs
    pods = sorted(se.pods, key=lambda p: p.name)
    
    return render_template('solution_engineer_view.html',
                         solution_engineer=se,
                         pods=pods)


@solution_engineers_bp.route('/solution-engineer/<int:id>/edit', methods=['GET', 'POST'])
def solution_engineer_edit(id):
    """Edit solution engineer details."""
    se = SolutionEngineer.query.options(
        db.joinedload(SolutionEngineer.pods)
    ).filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        alias = request.form.get('alias', '').strip()
        specialty = request.form.get('specialty', '').strip()
        pod_ids = request.form.getlist('pod_ids')
        
        if not name:
            flash('Solution Engineer name is required.', 'danger')
            return redirect(url_for('solution_engineers.solution_engineer_edit', id=id))
        
        se.name = name
        se.alias = alias if alias else None
        se.specialty = specialty if specialty else None
        
        # Update POD associations
        se.pods.clear()
        for pod_id in pod_ids:
            pod = db.session.get(POD, int(pod_id))
            if pod:
                se.pods.append(pod)
        
        db.session.commit()
        
        flash(f'Solution Engineer "{name}" updated successfully!', 'success')
        return redirect(url_for('solution_engineers.solution_engineer_view', id=se.id))
    
    # Get all PODs for the form
    all_pods = POD.query.order_by(POD.name).all()
    return render_template('solution_engineer_form.html', solution_engineer=se, all_pods=all_pods)


@solution_engineers_bp.route('/solution-engineer/<int:id>/delete', methods=['POST'])
def solution_engineer_delete(id):
    """Delete solution engineer."""
    se = SolutionEngineer.query.filter_by(id=id).first_or_404()
    
    se_name = se.name
    
    # Clear POD associations
    se.pods.clear()
    
    db.session.delete(se)
    db.session.commit()
    
    flash(f'Solution Engineer "{se_name}" deleted successfully.', 'success')
    return redirect(url_for('solution_engineers.solution_engineers_list'))

