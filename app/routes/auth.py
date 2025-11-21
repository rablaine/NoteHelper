"""
Authentication routes for NoteHelper.
Handles login, logout, Azure AD OAuth, and account linking.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
import msal
import requests

from app.models import db, User, WhitelistedDomain, AccountLinkingRequest, UserPreference, utc_now

# Create blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login')
def login():
    """Show login page or redirect to Entra ID login."""
    # If already authenticated, redirect to home
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # Check if Entra ID is configured
    if not current_app.config.get('AZURE_CLIENT_ID') or current_app.config['AZURE_CLIENT_ID'] == 'your-azure-client-id':
        # Entra ID not configured - show login page with instructions
        flash('Entra ID authentication is not configured. Please set up your Entra ID credentials in .env file.', 'warning')
        return render_template('login.html')
    
    # Create MSAL confidential client
    msal_app = msal.ConfidentialClientApplication(
        current_app.config['AZURE_CLIENT_ID'],
        authority=current_app.config['AZURE_AUTHORITY'],
        client_credential=current_app.config['AZURE_CLIENT_SECRET']
    )
    
    # Generate auth URL
    auth_url = msal_app.get_authorization_request_url(
        scopes=current_app.config['AZURE_SCOPE'],
        redirect_uri=current_app.config['AZURE_REDIRECT_URI']
    )
    
    return redirect(auth_url)


@auth_bp.route('/domain-not-allowed')
def domain_not_allowed():
    """Show error page for non-whitelisted domains."""
    email = request.args.get('email', 'your email')
    return render_template('domain_not_allowed.html', email=email)


@auth_bp.route('/auth/callback')
def auth_callback():
    """Handle Entra ID OAuth callback with domain whitelist and account linking support."""
    # Get authorization code from query params
    code = request.args.get('code')
    if not code:
        flash('Authentication failed: No authorization code received.', 'danger')
        return redirect(url_for('auth.login'))
    
    # Create MSAL confidential client
    msal_app = msal.ConfidentialClientApplication(
        current_app.config['AZURE_CLIENT_ID'],
        authority=current_app.config['AZURE_AUTHORITY'],
        client_credential=current_app.config['AZURE_CLIENT_SECRET']
    )
    
    # Exchange code for token
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=current_app.config['AZURE_SCOPE'],
        redirect_uri=current_app.config['AZURE_REDIRECT_URI']
    )
    
    if 'error' in result:
        flash(f"Authentication failed: {result.get('error_description', 'Unknown error')}", 'danger')
        return redirect(url_for('auth.login'))
    
    # Get user info from Microsoft Graph
    access_token = result['access_token']
    graph_response = requests.get(
        'https://graph.microsoft.com/v1.0/me',
        headers={'Authorization': f'Bearer {access_token}'}
    )
    
    if graph_response.status_code != 200:
        flash('Failed to retrieve user information from Microsoft Graph.', 'danger')
        return redirect(url_for('auth.login'))
    
    user_info = graph_response.json()
    azure_id = user_info['id']
    email = user_info.get('mail') or user_info.get('userPrincipalName')
    name = user_info.get('displayName', email)
    
    # Check if domain is whitelisted (for non-@microsoft.com accounts)
    if not WhitelistedDomain.is_domain_allowed(email):
        # Domain not allowed - redirect to error page
        return redirect(url_for('auth.domain_not_allowed', email=email))
    
    # Determine account type based on email domain
    is_microsoft_account = email.lower().endswith('@microsoft.com')
    
    # Try to find existing user by either azure_id (handles dual accounts)
    if is_microsoft_account:
        user = User.query.filter_by(microsoft_azure_id=azure_id).first()
    else:
        user = User.query.filter_by(external_azure_id=azure_id).first()
    
    if not user:
        # New Azure ID - check if there's an existing full account with this email
        # that might be waiting to link with this account type
        existing_full_account = User.query.filter_by(email=email, is_stub=False).first()
        
        if existing_full_account:
            # There's a full account with this email - check if they have the other account type
            if is_microsoft_account and not existing_full_account.microsoft_azure_id:
                # This is a Microsoft account trying to link to an external-only account
                # Redirect to first-time flow to ask if they want to link
                session['pending_auth'] = {
                    'azure_id': azure_id,
                    'email': email,
                    'name': name,
                    'is_microsoft': is_microsoft_account
                }
                return redirect(url_for('auth.first_time_flow'))
            elif not is_microsoft_account and not existing_full_account.external_azure_id:
                # This is an external account trying to link to a Microsoft-only account
                session['pending_auth'] = {
                    'azure_id': azure_id,
                    'email': email,
                    'name': name,
                    'is_microsoft': is_microsoft_account
                }
                return redirect(url_for('auth.first_time_flow'))
        
        # No existing account or incompatible account - show first-time flow
        session['pending_auth'] = {
            'azure_id': azure_id,
            'email': email,
            'name': name,
            'is_microsoft': is_microsoft_account
        }
        return redirect(url_for('auth.first_time_flow'))
    
    # User exists - update last login and email
    user.last_login = utc_now()
    user.name = name  # Update name in case it changed
    if is_microsoft_account:
        user.microsoft_email = email
    else:
        user.external_email = email
    
    # If this is a stub account, remind them they need to complete linking
    if user.is_stub:
        db.session.commit()
        login_user(user)
        flash('You are logged into a temporary account. Please complete the account linking process.', 'warning')
        return redirect(url_for('auth.account_link_status'))
    
    db.session.commit()
    
    # Log user in
    login_user(user)
    
    # Check if there are pending link requests for this user
    pending_requests = user.get_pending_link_requests()
    if pending_requests:
        flash(f'You have {len(pending_requests)} pending account linking request(s). Please review them in your profile.', 'info')
    
    flash(f'Welcome back, {user.name}!', 'success')
    return redirect(url_for('main.index'))


@auth_bp.route('/logout')
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash('You have been logged out.', 'info')
    
    # Redirect to Entra ID logout (optional - clears Entra ID session too)
    logout_url = f"{current_app.config['AZURE_AUTHORITY']}/oauth2/v2.0/logout?post_logout_redirect_uri={request.host_url}"
    return redirect(logout_url)


@auth_bp.route('/profile')
@login_required
def user_profile():
    """Display current user's profile information and pending link requests."""
    from datetime import date
    from app.models import AIConfig, AIUsage
    
    # Get pending link requests for this user's email
    pending_requests = current_user.get_pending_link_requests() if not current_user.is_stub else []
    
    # Get AI usage for today
    ai_config = AIConfig.query.first()
    ai_usage_today = None
    if ai_config and ai_config.enabled:
        today = date.today()
        usage = AIUsage.query.filter_by(user_id=current_user.id, date=today).first()
        ai_usage_today = {
            'used': usage.call_count if usage else 0,
            'limit': ai_config.max_daily_calls_per_user,
            'remaining': (ai_config.max_daily_calls_per_user - (usage.call_count if usage else 0))
        }
    
    return render_template('user_profile.html', 
                         user=current_user,
                         pending_requests=pending_requests,
                         ai_usage_today=ai_usage_today)


@auth_bp.route('/account/first-time')
def first_time_flow():
    """First-time login flow to determine if user wants to create new account or link to existing."""
    # Check if there's pending auth data in session
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('auth.login'))
    
    return render_template('first_time_flow.html',
                         email=pending_auth['email'],
                         name=pending_auth['name'],
                         is_microsoft=pending_auth['is_microsoft'])


@auth_bp.route('/account/first-time/new', methods=['POST'])
def first_time_new_user():
    """Create a new user account (first-time user with no existing data)."""
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('auth.login'))
    
    # Create new user account
    if pending_auth['is_microsoft']:
        user = User(
            microsoft_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            microsoft_email=pending_auth['email'],
            name=pending_auth['name']
        )
    else:
        user = User(
            external_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            external_email=pending_auth['email'],
            name=pending_auth['name']
        )
    
    db.session.add(user)
    db.session.commit()
    
    # Create default user preferences
    pref = UserPreference(user_id=user.id)
    db.session.add(pref)
    db.session.commit()
    
    # Clear pending auth
    session.pop('pending_auth', None)
    
    # Log user in
    login_user(user)
    flash(f'Welcome, {user.name}! Your account has been created.', 'success')
    
    return redirect(url_for('main.index'))


@auth_bp.route('/account/first-time/link', methods=['POST'])
def first_time_link_request():
    """Create a linking request to an existing account."""
    pending_auth = session.get('pending_auth')
    if not pending_auth:
        flash('No pending authentication. Please log in again.', 'warning')
        return redirect(url_for('auth.login'))
    
    target_email = request.form.get('target_email', '').strip()
    
    if not target_email or '@' not in target_email:
        flash('Please enter a valid email address.', 'danger')
        return redirect(url_for('auth.first_time_flow'))
    
    # Check if target email exists
    target_user = User.query.filter_by(email=target_email, is_stub=False).first()
    if not target_user:
        flash(f'No account found with email {target_email}. Double-check the spelling, or create a new account if this is your first time using the app.', 'warning')
        return redirect(url_for('auth.first_time_flow'))
    
    # Check if target user already has this account type linked
    is_microsoft = pending_auth['is_microsoft']
    if is_microsoft and target_user.microsoft_azure_id:
        flash(f'The account {target_email} already has a Microsoft account linked. Cannot link another Microsoft account.', 'danger')
        return redirect(url_for('auth.first_time_flow'))
    if not is_microsoft and target_user.external_azure_id:
        flash(f'The account {target_email} already has an external account linked. Cannot link another external account.', 'danger')
        return redirect(url_for('auth.first_time_flow'))
    
    # Create stub user
    if is_microsoft:
        stub_user = User(
            microsoft_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            microsoft_email=pending_auth['email'],
            name=pending_auth['name'],
            is_stub=True
        )
    else:
        stub_user = User(
            external_azure_id=pending_auth['azure_id'],
            email=pending_auth['email'],
            external_email=pending_auth['email'],
            name=pending_auth['name'],
            is_stub=True
        )
    
    db.session.add(stub_user)
    db.session.flush()
    
    # Cancel any existing pending requests from this stub to the same target
    AccountLinkingRequest.query.filter_by(
        requesting_user_id=stub_user.id,
        target_email=target_email,
        status='pending'
    ).update({'status': 'cancelled', 'resolved_at': utc_now()})
    
    # Create linking request
    link_request = AccountLinkingRequest(
        requesting_user_id=stub_user.id,
        target_email=target_email
    )
    db.session.add(link_request)
    db.session.commit()
    
    # Clear pending auth
    session.pop('pending_auth', None)
    
    # Log stub user in
    login_user(stub_user)
    
    flash(f'Linking request sent to {target_email}. Please log in with that account to approve the request.', 'success')
    return redirect(url_for('auth.account_link_status'))


@auth_bp.route('/account/link-status')
@login_required
def account_link_status():
    """Show status of account linking for stub users."""
    if not current_user.is_stub:
        return redirect(url_for('auth.user_profile'))
    
    # Get pending requests
    requests = AccountLinkingRequest.query.filter_by(
        requesting_user_id=current_user.id,
        status='pending'
    ).all()
    
    return render_template('account_link_status.html', requests=requests)


@auth_bp.route('/account/link/approve/<int:request_id>', methods=['POST'])
@login_required
def account_link_approve(request_id):
    """Approve a linking request and merge the stub account."""
    link_request = AccountLinkingRequest.query.get_or_404(request_id)
    
    # Verify this request is for the current user
    if link_request.target_email != current_user.email:
        flash('You cannot approve a linking request not intended for you.', 'danger')
        return redirect(url_for('auth.user_profile'))
    
    # Verify request is still pending
    if link_request.status != 'pending':
        flash('This linking request has already been processed.', 'info')
        return redirect(url_for('auth.user_profile'))
    
    # Get the stub user
    stub_user = db.session.get(User, link_request.requesting_user_id)
    if not stub_user or not stub_user.is_stub:
        flash('Invalid linking request.', 'danger')
        return redirect(url_for('auth.user_profile'))
    
    # Check if current user already has this account type
    if stub_user.microsoft_azure_id and current_user.microsoft_azure_id:
        flash('You already have a Microsoft account linked.', 'danger')
        return redirect(url_for('auth.user_profile'))
    if stub_user.external_azure_id and current_user.external_azure_id:
        flash('You already have an external account linked.', 'danger')
        return redirect(url_for('auth.user_profile'))
    
    # Clear stub's azure_ids before merging to avoid UNIQUE constraint violation
    stub_microsoft_id = stub_user.microsoft_azure_id
    stub_external_id = stub_user.external_azure_id
    stub_microsoft_email = stub_user.microsoft_email
    stub_external_email = stub_user.external_email
    stub_user.microsoft_azure_id = None
    stub_user.external_azure_id = None
    db.session.flush()  # Flush to release the UNIQUE constraint
    
    # Merge the accounts
    if stub_microsoft_id:
        current_user.microsoft_azure_id = stub_microsoft_id
        current_user.microsoft_email = stub_microsoft_email
    if stub_external_id:
        current_user.external_azure_id = stub_external_id
        current_user.external_email = stub_external_email
    
    current_user.linked_at = utc_now()
    
    # Save stub_id for deletion
    stub_user_id = stub_user.id
    
    # Mark request as approved
    link_request.status = 'approved'
    link_request.resolved_at = utc_now()
    link_request.resolved_by_user_id = current_user.id
    
    # Commit the merge and approval
    db.session.commit()
    
    # Delete stub user using raw SQL to preserve the foreign key in account_linking_requests
    # (Using ORM delete would NULL the FK)
    db.session.execute(db.text('DELETE FROM users WHERE id = :id'), {'id': stub_user_id})
    db.session.commit()
    
    flash('Account linked successfully! You can now log in with either account.', 'success')
    return redirect(url_for('auth.user_profile'))


@auth_bp.route('/account/link/deny/<int:request_id>', methods=['POST'])
@login_required
def account_link_deny(request_id):
    """Deny a linking request."""
    link_request = AccountLinkingRequest.query.get_or_404(request_id)
    
    # Verify this request is for the current user
    if link_request.target_email != current_user.email:
        flash('You cannot deny a linking request not intended for you.', 'danger')
        return redirect(url_for('auth.user_profile'))
    
    # Verify request is still pending
    if link_request.status != 'pending':
        flash('This linking request has already been processed.', 'info')
        return redirect(url_for('auth.user_profile'))
    
    # Mark request as denied
    link_request.status = 'denied'
    link_request.resolved_at = utc_now()
    link_request.resolved_by_user_id = current_user.id
    
    db.session.commit()
    
    flash('Linking request denied.', 'info')
    return redirect(url_for('auth.user_profile'))

