"""
Flask application factory for NoteHelper.
Single-user local deployment mode.
"""
import os
from flask import Flask, g
from flask_migrate import Migrate
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import db from models module
from app.models import db

# Initialize extensions
migrate = Migrate()


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///data/notehelper.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Import models to register them with SQLAlchemy
    from app import models
    
    # Create default user and preferences on first run
    @app.before_first_request
    def create_default_user():
        """Create single default user if database is empty."""
        from app.models import User, UserPreference
        
        user = User.query.first()
        if not user:
            user = User(
                email='user@localhost',
                name='Local User',
                is_admin=True  # Single user has all permissions
            )
            db.session.add(user)
            db.session.commit()
            
            # Create default preferences
            pref = UserPreference(user_id=user.id)
            db.session.add(pref)
            db.session.commit()
    
    # Load app-wide preferences into g
    @app.before_request
    def load_preferences():
        """Load single user and preferences into request context."""
        from app.models import User, UserPreference
        
        # Get the single user
        g.user = User.query.first()
        
        # Load preferences
        if g.user:
            g.user_prefs = UserPreference.query.filter_by(user_id=g.user.id).first()
            if not g.user_prefs:
                g.user_prefs = UserPreference(user_id=g.user.id)
                db.session.add(g.user_prefs)
                db.session.commit()
    
    # Register blueprints (skip auth blueprint - not needed in single-user mode)
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
