"""
Flask application factory for NoteHelper.
Initializes the app, extensions, and blueprints.
"""
import os
from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import db from models module
from app.models import db

# Initialize extensions
migrate = Migrate()
login_manager = LoginManager()


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Safety check: Prevent running without configuration
    if not app.config['SECRET_KEY']:
        raise ValueError("SECRET_KEY environment variable is not set")
    if not app.config['SQLALCHEMY_DATABASE_URI']:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    # Configure Flask-Login
    from app.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Import models to register them with SQLAlchemy
    from app import models
    
    # Before request handler for user data isolation and stub user restriction
    @app.before_request
    def before_request():
        """Handle stub user restrictions and load user preferences before each request."""
        from flask import g, request, redirect, url_for
        
        # If user is logged in but is a stub account, restrict access to only account linking routes
        # This check happens BEFORE LOGIN_DISABLED check so tests can verify stub restrictions
        if current_user.is_authenticated and current_user.is_stub:
            stub_allowed_routes = ['auth.account_link_status', 'auth.first_time_flow', 'auth.first_time_new_user', 
                                  'auth.first_time_link_request', 'auth.user_profile', 'auth.logout', 'static']
            if request.endpoint not in stub_allowed_routes:
                return redirect(url_for('auth.account_link_status'))
        
        # Load user preferences
        if current_user.is_authenticated:
            g.user_prefs = models.UserPreference.query.filter_by(user_id=current_user.id).first()
            if not g.user_prefs:
                # Create default preferences if they don't exist
                g.user_prefs = models.UserPreference(user_id=current_user.id)
                db.session.add(g.user_prefs)
                db.session.commit()
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.ai import ai_bp
    from app.routes.territories import territories_bp
    from app.routes.pods import pods_bp
    from app.routes.solution_engineers import solution_engineers_bp
    from app.routes.sellers import sellers_bp
    from app.routes.customers import customers_bp
    from app.routes.topics import topics_bp
    from app.routes.call_logs import call_logs_bp
    from app.routes.main import main_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(territories_bp)
    app.register_blueprint(pods_bp)
    app.register_blueprint(solution_engineers_bp)
    app.register_blueprint(sellers_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(topics_bp)
    app.register_blueprint(call_logs_bp)
    app.register_blueprint(main_bp)
    
    return app
