from datetime import datetime, timedelta
import os
from flask import Flask, render_template
from flask_login import LoginManager
from importlib import import_module
from flask_sqlalchemy import SQLAlchemy

# Set the application start time in environment variables
if not os.getenv('APP_START_TIME'):
    os.environ['APP_START_TIME'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Initialize Flask extensions
db = SQLAlchemy()
login_manager = LoginManager()

# Function to register Flask extensions
def register_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)

# Function to configure database
def configure_database(app):
    initialized = False

    @app.before_request
    def initialize_database():
        nonlocal initialized
        if not initialized:
            db.create_all()
            initialized = True

    @app.teardown_request
    def shutdown_session(exception=None):
        db.session.remove()

# Function to set the secret key for Flask app
def set_secret_key(app):
    app.secret_key = 'my_secret_key'

# Function to set the session timeout
def set_session_timeout(app):
    app.permanent_session_lifetime = timedelta(minutes=30)

# Function to register Flask blueprints
def register_blueprints(app):
    # Import and register blueprints from various modules
    for module_name in ('auth', 'settings', 'home', 'vmware'):
        module = import_module('apps.{}.routes'.format(module_name))
        app.register_blueprint(module.blueprint)

# Function to create Flask application
def create_app(config):
    # Create Flask app instance
    app = Flask(__name__)
    # Load configuration from config object
    app.config.from_object(config)
    # Register Flask extensions
    register_extensions(app)
    # Set session timeout
    set_session_timeout(app)
    # Set secret key
    set_secret_key(app)
    # Register Flask blueprints
    register_blueprints(app)
    # Configure database
    configure_database(app)
    # Return Flask app instance
    return app

# Define a custom unauthorized handler function for Flask-Login
@login_manager.unauthorized_handler
def unauthorized():
    # Customize the unauthorized page here
    return render_template('error/403.html')