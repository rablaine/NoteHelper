"""
Call log routes for NoteHelper.
Handles call log listing, creation, viewing, editing, and Fill My Day bulk import.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from datetime import datetime
import logging

from app.models import db, CallLog, Customer, Seller, Territory, Topic, Partner, Milestone, MsxTask, UserPreference
from app.services.msx_api import create_task, TASK_CATEGORIES

logger = logging.getLogger(__name__)

# Create blueprint
call_logs_bp = Blueprint('call_logs', __name__)


def _handle_milestone_and_task(call_log, user_id):
    """
    Handle MSX milestone selection and optional task creation.
    
    Reads form data for milestone info and creates/links the milestone.
    If task fields are provided, creates the task in MSX and stores it locally.
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    # Get MSX milestone data from form
    milestone_msx_id = request.form.get('milestone_msx_id', '').strip()
    milestone_url = request.form.get('milestone_url', '').strip()
    
    if not milestone_msx_id:
        # No milestone selected - clear any existing
        call_log.milestones = []
        return True, None
    
    # Get additional milestone metadata
    milestone_name = request.form.get('milestone_name', '').strip()
    milestone_number = request.form.get('milestone_number', '').strip()
    milestone_status = request.form.get('milestone_status', '').strip()
    milestone_status_code = request.form.get('milestone_status_code', '').strip()
    milestone_opp_name = request.form.get('milestone_opportunity_name', '').strip()
    
    # Get customer for milestone association
    customer_id = request.form.get('customer_id')
    
    # Find or create milestone by MSX ID
    milestone = Milestone.query.filter_by(msx_milestone_id=milestone_msx_id).first()
    if not milestone:
        # Create new milestone
        milestone = Milestone(
            msx_milestone_id=milestone_msx_id,
            url=milestone_url,
            milestone_number=milestone_number,
            title=milestone_name,
            msx_status=milestone_status,
            msx_status_code=int(milestone_status_code) if milestone_status_code else None,
            opportunity_name=milestone_opp_name,
            customer_id=int(customer_id) if customer_id else None,
            user_id=user_id
        )
        db.session.add(milestone)
    else:
        # Update existing milestone with latest data
        if milestone_name:
            milestone.title = milestone_name
        if milestone_url:
            milestone.url = milestone_url
        if milestone_status:
            milestone.msx_status = milestone_status
        if milestone_status_code:
            milestone.msx_status_code = int(milestone_status_code)
        if milestone_opp_name:
            milestone.opportunity_name = milestone_opp_name
    
    # Associate milestone with call log
    call_log.milestones = [milestone]
    
    # Check if a task was already created (via the "Create Task in MSX" button)
    created_task_id = request.form.get('created_task_id', '').strip()
    
    if created_task_id:
        # Task was pre-created - just store the local record
        task_subject = request.form.get('task_subject', '').strip()
        task_category = request.form.get('task_category', '').strip()
        task_duration = request.form.get('task_duration', '60')
        task_description = request.form.get('task_description', '').strip()
        task_due_date_str = request.form.get('task_due_date', '').strip()
        created_task_url = request.form.get('created_task_url', '').strip()
        created_task_category_name = request.form.get('created_task_category_name', '').strip()
        created_task_is_hok = request.form.get('created_task_is_hok', '').strip() == '1'
        
        try:
            duration_minutes = int(task_duration)
        except (ValueError, TypeError):
            duration_minutes = 60
        
        try:
            task_category_int = int(task_category) if task_category else 0
        except (ValueError, TypeError):
            task_category_int = 0
        
        logger.info(f"Linking pre-created MSX task {created_task_id} to call log")
        
        # Parse due date
        task_due_date = None
        if task_due_date_str:
            try:
                task_due_date = datetime.strptime(task_due_date_str, '%Y-%m-%d')
            except ValueError:
                pass
        
        msx_task = MsxTask(
            msx_task_id=created_task_id,
            msx_task_url=created_task_url,
            subject=task_subject,
            description=task_description if task_description else None,
            task_category=task_category_int,
            task_category_name=created_task_category_name or 'Unknown',
            duration_minutes=duration_minutes,
            is_hok=created_task_is_hok,
            due_date=task_due_date,
            call_log=call_log,
            milestone=milestone
        )
        db.session.add(msx_task)
        logger.info(f"Pre-created MSX task linked successfully: {created_task_id}")
    else:
        # Check if task creation is requested (create on save - fallback behavior)
        task_subject = request.form.get('task_subject', '').strip()
        task_category = request.form.get('task_category', '').strip()
        
        if task_subject and task_category:
            # Create task in MSX
            task_duration = request.form.get('task_duration', '60')
            task_description = request.form.get('task_description', '').strip()
            task_due_date_str = request.form.get('task_due_date', '').strip()
            
            try:
                duration_minutes = int(task_duration)
            except (ValueError, TypeError):
                duration_minutes = 60
            
            # Build due date for MSX (ISO 8601)
            msx_due_date = None
            task_due_date = None
            if task_due_date_str:
                try:
                    task_due_date = datetime.strptime(task_due_date_str, '%Y-%m-%d')
                    msx_due_date = task_due_date.strftime('%Y-%m-%dT23:59:59Z')
                except ValueError:
                    pass
            
            logger.info(f"Creating MSX task on milestone {milestone_msx_id}: {task_subject}")
            
            result = create_task(
                milestone_id=milestone_msx_id,
                subject=task_subject,
                task_category=int(task_category),
                duration_minutes=duration_minutes,
                description=task_description if task_description else None,
                due_date=msx_due_date
            )
            
            if result.get('success'):
                # Store task locally
                task_category_info = next(
                    (c for c in TASK_CATEGORIES if c['code'] == int(task_category)), 
                    {'name': 'Unknown', 'is_hok': False}
                )
                
                msx_task = MsxTask(
                    msx_task_id=result.get('task_id'),
                    msx_task_url=result.get('task_url'),
                    subject=task_subject,
                    description=task_description if task_description else None,
                    task_category=int(task_category),
                    task_category_name=task_category_info['name'],
                    duration_minutes=duration_minutes,
                    is_hok=task_category_info['is_hok'],
                    due_date=task_due_date,
                    call_log=call_log,
                    milestone=milestone
                )
                db.session.add(msx_task)
                logger.info(f"MSX task created successfully: {result.get('task_id')}")
            else:
                error_msg = result.get('error', 'Unknown error creating task')
                logger.error(f"Failed to create MSX task: {error_msg}")
                # Don't fail the whole save, just log the error and flash a warning
                flash(f'Call log saved, but task creation failed: {error_msg}', 'warning')
    
    return True, None


@call_logs_bp.route('/call-logs')
def call_logs_list():
    """List all call logs (FR010)."""
    call_logs = CallLog.query.options(
        db.joinedload(CallLog.customer).joinedload(Customer.seller),
        db.joinedload(CallLog.customer).joinedload(Customer.territory),
        db.joinedload(CallLog.topics),
        db.joinedload(CallLog.partners)
    ).order_by(CallLog.call_date.desc()).all()
    return render_template('call_logs_list.html', call_logs=call_logs)


@call_logs_bp.route('/call-log/new', methods=['GET', 'POST'])
def call_log_create():
    """Create a new call log (FR005)."""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        partner_ids = request.form.getlist('partner_ids')
        referrer = request.form.get('referrer', '')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        # Parse call date and time
        call_time_str = request.form.get('call_time', '')
        try:
            if call_time_str:
                call_date = datetime.strptime(f'{call_date_str} {call_time_str}', '%Y-%m-%d %H:%M')
            else:
                call_date = datetime.strptime(call_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date/time format.', 'danger')
            return redirect(url_for('call_logs.call_log_create'))
        
        # Get customer and auto-fill territory
        customer = Customer.query.filter_by(id=int(customer_id)).first()
        territory_id = customer.territory_id if customer else None
        
        # If customer doesn't have a seller but one is selected, associate it
        if customer and not customer.seller_id and seller_id:
            customer.seller_id = int(seller_id)
            # Also update customer's territory if seller has one
            seller = Seller.query.filter_by(id=int(seller_id)).first()
            if seller and seller.territory_id:
                customer.territory_id = seller.territory_id
                territory_id = seller.territory_id
        
        # Create call log
        call_log = CallLog(
            customer_id=int(customer_id),
            call_date=call_date,
            content=content,
            user_id=g.user.id)
        
        # Add topics
        if topic_ids:
            topics = Topic.query.filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics.extend(topics)
        
        # Add partners
        if partner_ids:
            partners = Partner.query.filter(Partner.id.in_([int(pid) for pid in partner_ids])).all()
            call_log.partners.extend(partners)
        
        db.session.add(call_log)
        
        # Handle milestone and optional task creation
        _handle_milestone_and_task(call_log, g.user.id)
        
        db.session.commit()
        
        flash('Call log created successfully!', 'success')
        
        # Redirect back to referrer if provided
        if referrer:
            return redirect(referrer)
        
        return redirect(url_for('call_logs.call_log_view', id=call_log.id))
    
    # GET request - load form
    # Require customer_id to be specified
    preselect_customer_id = request.args.get('customer_id', type=int)
    
    if not preselect_customer_id:
        # Redirect to customers list to select a customer first
        flash('Please select a customer before creating a call log.', 'info')
        return redirect(url_for('customers.customers_list'))
    
    # Load customer and their previous call logs
    preselect_customer = Customer.query.filter_by(id=preselect_customer_id).first_or_404()
    previous_calls = CallLog.query.filter_by(customer_id=preselect_customer_id).options(
        db.joinedload(CallLog.topics)
    ).order_by(CallLog.call_date.desc()).all()
    
    customers = Customer.query.order_by(Customer.name).all()
    sellers = Seller.query.order_by(Seller.name).all()
    topics = Topic.query.order_by(Topic.name).all()
    partners = Partner.query.order_by(Partner.name).all()
    
    # Pre-select topic from query params
    preselect_topic_id = request.args.get('topic_id', type=int)
    
    # Capture referrer for redirect after creation
    referrer = request.referrer or ''
    
    # Pass date and time (from query param or now)
    from datetime import date
    date_param = request.args.get('date', '')
    if date_param:
        # Validate date format
        try:
            datetime.strptime(date_param, '%Y-%m-%d')
            today = date_param
        except ValueError:
            today = date.today().strftime('%Y-%m-%d')
    else:
        today = date.today().strftime('%Y-%m-%d')
    
    # Current time for new call logs (default to now)
    now_time = datetime.now().strftime('%H:%M')
    
    # Check if AI features are enabled
    from app.routes.ai import is_ai_enabled
    ai_enabled = is_ai_enabled()
    
    # Get user's custom WorkIQ prompt (for meeting import modal)
    from app.services.workiq_service import DEFAULT_SUMMARY_PROMPT
    user_id = g.user.id if g.user.is_authenticated else 1
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    user_prompt = pref.workiq_summary_prompt if pref and pref.workiq_summary_prompt else DEFAULT_SUMMARY_PROMPT
    
    return render_template('call_log_form.html', 
                         call_log=None, 
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         partners=partners,
                         preselect_customer_id=preselect_customer_id,
                         preselect_customer=preselect_customer,
                         preselect_topic_id=preselect_topic_id,
                         previous_calls=previous_calls,
                         referrer=referrer,
                         today=today,
                         now_time=now_time,
                         ai_enabled=ai_enabled,
                         workiq_prompt=user_prompt,
                         default_workiq_prompt=DEFAULT_SUMMARY_PROMPT)


@call_logs_bp.route('/call-log/<int:id>')
def call_log_view(id):
    """View call log details (FR010)."""
    call_log = CallLog.query.filter_by(id=id).first_or_404()
    return render_template('call_log_view.html', call_log=call_log)


@call_logs_bp.route('/call-log/<int:id>/edit', methods=['GET', 'POST'])
def call_log_edit(id):
    """Edit call log (FR010)."""
    call_log = CallLog.query.filter_by(id=id).first_or_404()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        seller_id = request.form.get('seller_id')
        call_date_str = request.form.get('call_date')
        content = request.form.get('content', '').strip()
        topic_ids = request.form.getlist('topic_ids')
        partner_ids = request.form.getlist('partner_ids')
        
        # Validation
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        if not call_date_str:
            flash('Call date is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        if not content:
            flash('Call log content is required.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        # Parse call date and time
        call_time_str = request.form.get('call_time', '')
        try:
            if call_time_str:
                call_date = datetime.strptime(f'{call_date_str} {call_time_str}', '%Y-%m-%d %H:%M')
            else:
                call_date = datetime.strptime(call_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date/time format.', 'danger')
            return redirect(url_for('call_logs.call_log_edit', id=id))
        
        # Update call log
        call_log.customer_id = int(customer_id)
        # Seller and territory are now derived from customer
        call_log.call_date = call_date
        call_log.content = content
        
        # Update topics - remove all existing associations first
        call_log.topics = []
        if topic_ids:
            topics = Topic.query.filter(Topic.id.in_([int(tid) for tid in topic_ids])).all()
            call_log.topics = topics
        
        # Update partners - remove all existing associations first
        call_log.partners = []
        if partner_ids:
            partners = Partner.query.filter(Partner.id.in_([int(pid) for pid in partner_ids])).all()
            call_log.partners = partners
        
        # Handle milestone and optional task creation
        _handle_milestone_and_task(call_log, g.user.id)
        
        db.session.commit()
        
        flash('Call log updated successfully!', 'success')
        return redirect(url_for('call_logs.call_log_view', id=call_log.id))
    
    # GET request - load form
    customers = Customer.query.order_by(Customer.name).all()
    sellers = Seller.query.order_by(Seller.name).all()
    topics = Topic.query.order_by(Topic.name).all()
    partners = Partner.query.order_by(Partner.name).all()
    
    # Load AI config for AI button visibility
    from app.routes.ai import is_ai_enabled
    ai_enabled = is_ai_enabled()
    
    return render_template('call_log_form.html',
                         ai_enabled=ai_enabled,
                         call_log=call_log,
                         customers=customers,
                         sellers=sellers,
                         topics=topics,
                         partners=partners,
                         preselect_customer_id=None,
                         preselect_topic_id=None)


@call_logs_bp.route('/call-log/<int:id>/delete', methods=['POST'])
def call_log_delete(id):
    """Delete a call log."""
    call_log = db.session.get(CallLog, id)
    
    if not call_log:
        flash('Call log not found.', 'danger')
        return redirect(url_for('call_logs.call_logs_list'))
    
    # Store customer for redirect
    customer_id = call_log.customer_id
    
    # Delete the call log
    db.session.delete(call_log)
    db.session.commit()
    
    flash('Call log deleted successfully.', 'success')
    
    # Redirect to customer view if we have a customer, otherwise call logs list
    if customer_id:
        return redirect(url_for('customers.customer_view', id=customer_id))
    else:
        return redirect(url_for('call_logs.call_logs_list'))


# =============================================================================
# Meeting Import API (WorkIQ Integration)
# =============================================================================

@call_logs_bp.route('/api/meetings')
def api_get_meetings():
    """
    Get meetings for a specific date with optional fuzzy matching.
    
    Query params:
        date: Date in YYYY-MM-DD format (required)
        customer_name: Customer name to fuzzy match against (optional)
        
    Returns JSON:
        - meetings: List of meeting objects
        - auto_selected_index: Index of fuzzy-matched meeting (or null)
        - auto_selected_reason: Explanation of why meeting was selected
    """
    from flask import jsonify
    from app.services.workiq_service import get_meetings_for_date, find_best_customer_match
    
    date_str = request.args.get('date')
    customer_name = request.args.get('customer_name', '')
    
    if not date_str:
        return jsonify({'error': 'date parameter is required'}), 400
    
    # Validate date format
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Get meetings from WorkIQ
    try:
        meetings = get_meetings_for_date(date_str)
    except Exception as e:
        logger.error(f"WorkIQ error: {e}")
        return jsonify({'error': f'Failed to fetch meetings: {str(e)}'}), 500
    
    # Format for API response
    formatted_meetings = []
    for m in meetings:
        formatted_meetings.append({
            'id': m.get('id', ''),
            'title': m.get('title', ''),
            'start_time': m['start_time'].isoformat() if m.get('start_time') else None,
            'start_time_display': m['start_time'].strftime('%I:%M %p') if m.get('start_time') else m.get('start_time_str', ''),
            'customer': m.get('customer', ''),
            'attendees': m.get('attendees', [])
        })
    
    # Find best match if customer name provided
    auto_selected = None
    auto_selected_reason = None
    
    if customer_name and meetings:
        match_idx = find_best_customer_match(meetings, customer_name)
        if match_idx is not None:
            auto_selected = match_idx
            matched = meetings[match_idx]
            auto_selected_reason = f"Auto-selected: '{matched.get('customer') or matched.get('title')}' matches '{customer_name}'"
    
    return jsonify({
        'meetings': formatted_meetings,
        'auto_selected_index': auto_selected,
        'auto_selected_reason': auto_selected_reason,
        'date': date_str,
        'customer_name': customer_name
    })


@call_logs_bp.route('/api/meetings/summary')
def api_get_meeting_summary():
    """
    Get a 250-word summary for a specific meeting.
    
    Query params:
        title: Meeting title (required)
        date: Date in YYYY-MM-DD format (optional, helps narrow down)
        prompt: Custom prompt template (optional, uses {title} and {date} placeholders)
        
    Returns JSON:
        - summary: The 250-word meeting summary
        - topics: List of technologies/topics discussed
        - action_items: List of follow-up items
    """
    from flask import jsonify
    from app.services.workiq_service import get_meeting_summary
    
    title = request.args.get('title')
    date_str = request.args.get('date')
    custom_prompt = request.args.get('prompt')
    
    if not title:
        return jsonify({'error': 'title parameter is required'}), 400
    
    try:
        result = get_meeting_summary(title, date_str, custom_prompt=custom_prompt)
        return jsonify({
            'summary': result.get('summary', ''),
            'topics': result.get('topics', []),
            'action_items': result.get('action_items', []),
            'success': True
        })
    except Exception as e:
        logger.error(f"Failed to get meeting summary: {e}")
        return jsonify({
            'error': f'Failed to fetch summary: {str(e)}',
            'success': False
        }), 500


# =============================================================================
# Fill My Day (Bulk Meeting Import)
# =============================================================================

@call_logs_bp.route('/fill-my-day')
def fill_my_day():
    """Fill My Day page - bulk import meetings for a date into call logs."""
    from datetime import date as date_type
    date_param = request.args.get('date', '')
    
    # Validate date if provided
    if date_param:
        try:
            datetime.strptime(date_param, '%Y-%m-%d')
        except ValueError:
            date_param = ''
    
    return render_template('fill_my_day.html', prefill_date=date_param)


@call_logs_bp.route('/api/fill-my-day/process', methods=['POST'])
def api_fill_my_day_process():
    """
    Process a single meeting for Fill My Day.
    
    Fetches the summary from WorkIQ and runs AI analysis.
    Called per-meeting to show progress in the UI.
    
    Request JSON:
        - meeting: Meeting object {title, start_time, customer, ...}
        - date: Date string YYYY-MM-DD
        - customer_id: Matched customer ID
        
    Returns JSON:
        - summary: Meeting summary text
        - content_html: Formatted HTML for call notes
        - topics: List of {id, name} suggested topics
        - task_subject: Suggested task subject
        - task_description: Suggested task description
        - success: bool
    """
    from app.services.workiq_service import get_meeting_summary
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    meeting = data.get('meeting', {})
    date_str = data.get('date', '')
    title = meeting.get('title', '')
    
    if not title:
        return jsonify({'success': False, 'error': 'Meeting title is required'}), 400
    
    customer_id = data.get('customer_id')

    result = {'success': True, 'summary': '', 'content_html': '', 'topics': [],
              'task_subject': '', 'task_description': '', 'summary_ok': False,
              'milestone': None}
    
    # Step 1: Get meeting summary
    try:
        summary_data = get_meeting_summary(title, date_str)
        summary = summary_data.get('summary', '')
        action_items = summary_data.get('action_items', [])
        
        # Build HTML content
        content_html = f'<h2>{title}</h2>'
        content_html += '<p><strong>Summary:</strong></p>'
        content_html += f'<p>{summary}</p>'
        if action_items:
            content_html += '<p><strong>Action Items:</strong></p><ul>'
            for item in action_items:
                content_html += f'<li>{item}</li>'
            content_html += '</ul>'
        
        result['summary'] = summary
        result['content_html'] = content_html
        result['summary_ok'] = bool(summary and not summary.startswith('Error'))
    except Exception as e:
        logger.error(f"Fill My Day - summary error for '{title}': {e}")
        result['summary'] = f'[Could not fetch summary: {str(e)}]'
        result['content_html'] = f'<h2>{title}</h2><p><em>Summary unavailable</em></p>'
    
    # Step 2: AI analysis (topics + task suggestion) - only if we got a real summary
    ai_client = None
    deployment_name = None
    if result['summary_ok']:
        try:
            from app.routes.ai import get_azure_openai_client, get_openai_deployment, is_ai_enabled
            
            deployment_name = get_openai_deployment()
            if is_ai_enabled():
                ai_client = get_azure_openai_client()
                if ai_client:
                    # Analyze call for topics
                    all_topics = Topic.query.order_by(Topic.name).all()
                    topic_names = [t.name for t in all_topics]
                    
                    prompt = f"""Analyze this meeting summary and identify relevant technology topics.

Available topics: {', '.join(topic_names)}

Meeting summary:
{result['summary']}

Also suggest a brief task subject (1 line) and task description (2-3 lines) for follow-up work.

Return JSON format:
{{"topics": ["topic1", "topic2"], "task_subject": "...", "task_description": "..."}}"""
                    
                    response = ai_client.chat.completions.create(
                        model=deployment_name,
                        messages=[{'role': 'user', 'content': prompt}],
                        temperature=0.3,
                        max_tokens=500,
                        response_format={"type": "json_object"}
                    )
                    
                    import json
                    ai_result = json.loads(response.choices[0].message.content)
                    
                    # Match topic names to IDs
                    matched_topics = []
                    for topic_name in ai_result.get('topics', []):
                        for t in all_topics:
                            if t.name.lower() == topic_name.lower():
                                matched_topics.append({'id': t.id, 'name': t.name})
                                break
                    
                    result['topics'] = matched_topics
                    result['task_subject'] = ai_result.get('task_subject', '')
                    result['task_description'] = ai_result.get('task_description', '')
        except Exception as e:
            logger.warning(f"Fill My Day - AI analysis error for '{title}': {e}")
            # Non-fatal - continue without AI enrichment
    
    # Step 3: Milestone matching - fetch from MSX and AI-match
    if result['summary_ok'] and customer_id:
        try:
            from app.services.msx_api import extract_account_id_from_url, get_milestones_by_account
            
            customer = db.session.get(Customer, int(customer_id))
            if customer and customer.tpid_url:
                account_id = extract_account_id_from_url(customer.tpid_url)
                if account_id:
                    msx_result = get_milestones_by_account(account_id)
                    if msx_result.get('success') and msx_result.get('milestones'):
                        milestones = msx_result['milestones']
                        
                        # AI match if we have a client and milestones
                        if ai_client and len(milestones) > 0:
                            milestone_list = "\n".join([
                                f"- ID: {m['id']}, Name: {m['name']}, Status: {m['status']}, "
                                f"Opportunity: {m.get('opportunity_name', '')}, "
                                f"Workload: {m.get('workload', '')}"
                                for m in milestones
                            ])
                            
                            ms_prompt = f"""Match these call notes to the most relevant milestone.

Call Notes:
{result['summary'][:2000]}

Available Milestones:
{milestone_list}

Which milestone best matches what was discussed? Also suggest a task subject and description
specifically for this milestone.

Return JSON:
{{"milestone_id": "THE_ID_OR_NULL", "reason": "why", "task_subject": "...", "task_description": "..."}}"""
                            
                            ms_response = ai_client.chat.completions.create(
                                model=deployment_name,
                                messages=[{'role': 'user', 'content': ms_prompt}],
                                temperature=0.3,
                                max_tokens=300,
                                response_format={"type": "json_object"}
                            )
                            
                            ms_ai = json.loads(ms_response.choices[0].message.content)
                            matched_id = ms_ai.get('milestone_id')
                            
                            if matched_id:
                                # Find the matched milestone data
                                matched = next(
                                    (m for m in milestones if m['id'] == matched_id),
                                    None
                                )
                                if matched:
                                    result['milestone'] = {
                                        'msx_milestone_id': matched['id'],
                                        'name': matched['name'],
                                        'number': matched.get('number', ''),
                                        'status': matched['status'],
                                        'status_code': matched.get('status_code'),
                                        'opportunity_name': matched.get('opportunity_name', ''),
                                        'url': matched.get('url', ''),
                                        'workload': matched.get('workload', ''),
                                        'reason': ms_ai.get('reason', '')
                                    }
                                    # Use milestone-specific task if provided
                                    if ms_ai.get('task_subject'):
                                        result['task_subject'] = ms_ai['task_subject']
                                    if ms_ai.get('task_description'):
                                        result['task_description'] = ms_ai['task_description']
        except Exception as e:
            logger.warning(f"Fill My Day - milestone matching error for '{title}': {e}")
            # Non-fatal - continue without milestone
    
    return jsonify(result)


@call_logs_bp.route('/api/fill-my-day/save', methods=['POST'])
def api_fill_my_day_save():
    """
    Save a single call log from Fill My Day.
    
    Request JSON:
        - customer_id: int
        - call_date: YYYY-MM-DD
        - call_time: HH:MM (optional)
        - content: HTML content
        - topic_ids: list of int
        - milestone: dict with MSX milestone data (optional)
        - task_subject: str (optional)
        - task_description: str (optional)
        
    Returns JSON:
        - success: bool
        - call_log_id: int
        - view_url: str
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    customer_id = data.get('customer_id')
    call_date_str = data.get('call_date', '')
    call_time_str = data.get('call_time', '')
    content = data.get('content', '').strip()
    topic_ids = data.get('topic_ids', [])
    milestone_data = data.get('milestone')
    task_subject = data.get('task_subject', '').strip()
    task_description = data.get('task_description', '').strip()
    created_task_id = data.get('created_task_id', '').strip()
    created_task_url = data.get('created_task_url', '').strip()
    created_task_category_name = data.get('created_task_category_name', '').strip()
    created_task_is_hok = data.get('created_task_is_hok', '').strip() == '1'
    task_due_date_str = data.get('task_due_date', '').strip()
    
    # Validation
    if not customer_id:
        return jsonify({'success': False, 'error': 'Customer is required'}), 400
    if not call_date_str:
        return jsonify({'success': False, 'error': 'Date is required'}), 400
    if not content:
        return jsonify({'success': False, 'error': 'Content is required'}), 400
    
    # Parse date/time
    try:
        if call_time_str:
            call_date = datetime.strptime(f'{call_date_str} {call_time_str}', '%Y-%m-%d %H:%M')
        else:
            call_date = datetime.strptime(call_date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid date/time format'}), 400
    
    # Verify customer exists
    customer = db.session.get(Customer, int(customer_id))
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404
    
    try:
        # Create call log
        call_log = CallLog(
            customer_id=int(customer_id),
            call_date=call_date,
            content=content,
            user_id=g.user.id
        )
        db.session.add(call_log)
        
        # Add topics
        if topic_ids:
            topics = Topic.query.filter(
                Topic.id.in_([int(tid) for tid in topic_ids])
            ).all()
            call_log.topics.extend(topics)
        
        # Link milestone if provided
        if milestone_data and milestone_data.get('msx_milestone_id'):
            msx_id = milestone_data['msx_milestone_id']
            milestone = Milestone.query.filter_by(msx_milestone_id=msx_id).first()
            if not milestone:
                milestone = Milestone(
                    msx_milestone_id=msx_id,
                    url=milestone_data.get('url', ''),
                    milestone_number=milestone_data.get('number', ''),
                    title=milestone_data.get('name', ''),
                    msx_status=milestone_data.get('status', ''),
                    msx_status_code=milestone_data.get('status_code'),
                    opportunity_name=milestone_data.get('opportunity_name', ''),
                    customer_id=int(customer_id),
                    user_id=g.user.id
                )
                db.session.add(milestone)
            else:
                # Update with latest data
                if milestone_data.get('name'):
                    milestone.title = milestone_data['name']
                if milestone_data.get('status'):
                    milestone.msx_status = milestone_data['status']
                if milestone_data.get('opportunity_name'):
                    milestone.opportunity_name = milestone_data['opportunity_name']
            
            call_log.milestones = [milestone]
        
        # Link pre-created MSX task if provided
        if created_task_id and milestone_data and milestone_data.get('msx_milestone_id'):
            msx_id = milestone_data['msx_milestone_id']
            milestone = Milestone.query.filter_by(msx_milestone_id=msx_id).first()
            if milestone:
                task_due_date = None
                if task_due_date_str:
                    try:
                        task_due_date = datetime.strptime(task_due_date_str, '%Y-%m-%d')
                    except ValueError:
                        pass
                
                msx_task = MsxTask(
                    msx_task_id=created_task_id,
                    msx_task_url=created_task_url,
                    subject=task_subject,
                    description=task_description if task_description else None,
                    task_category=0,  # Category code not passed from fill-my-day
                    task_category_name=created_task_category_name or 'Unknown',
                    duration_minutes=60,
                    is_hok=created_task_is_hok,
                    due_date=task_due_date,
                    call_log=call_log,
                    milestone=milestone
                )
                db.session.add(msx_task)
                logger.info(f"Fill My Day - linked task {created_task_id} to call log")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'call_log_id': call_log.id,
            'view_url': url_for('call_logs.call_log_view', id=call_log.id)
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Fill My Day - save error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
