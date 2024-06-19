from datetime import datetime
import time
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from flask_migrate import Migrate
from flask import render_template, session
from apps.config import config_dict, Config
from apps.home.util import get_esxi_ip, is_reachable
from apps.models import User, Group, DefaultVmSettingsModel, ConfigModel, NonDomainModel, DomainModel
from apps import create_app, db
from werkzeug.security import generate_password_hash

# Initialize directories
required_dirs = [
    'logs',
    'logs/build_logs',
    'apps/backups'
]

for directory in required_dirs:
    if not os.path.exists(directory):
        os.makedirs(directory)

# Configuration / Change this to True to run in Development mode
DEBUG = False

get_config_mode = 'Debug' if DEBUG else 'Production'
app_config = config_dict[get_config_mode.capitalize()]
app = create_app(app_config)

# Initialize database migration
Migrate(app, db)

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

    # Get admin user credentials from configuration
    username = Config.APP_ADMIN_USER
    password = Config.APP_ADMIN_PASSWORD

    # Check if the admin user exists in the database
    existing_user = db.session.query(User).filter_by(username=username).first()
    if existing_user:
        # If the user exists, update the password hash
        existing_user.set_password(password)
    else:
        # If the user doesn't exist, create a new user with the hashed password
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()

# Set up user groups (Administrators and Readers)
with app.app_context():
    admin_group = Group.query.filter_by(name='Administrators').first()
    if not admin_group:
        admin_group = Group(name='Administrators', description='Group for administrative users')
        db.session.add(admin_group)

    reader_group = Group.query.filter_by(name='Readers').first()
    if not reader_group:
        reader_group = Group(name='Readers', description='Group for read-only users')
        db.session.add(reader_group)

    # Add the admin user to the Administrators group
    if existing_user:
        db.session.add(existing_user)
        if admin_group not in existing_user.groups:
            admin_group.users.append(existing_user)
    else:
        db.session.add(new_user)
        if admin_group not in new_user.groups:
            admin_group.users.append(new_user)

    db.session.commit()

# Create default VM settings if they don't exist
with app.app_context():
    db.create_all()

    # Check if default settings already exist
    existing_default_settings = db.session.get(DefaultVmSettingsModel, 1)
    if not existing_default_settings:
        # If not, create default settings with ID 1
        default_settings = DefaultVmSettingsModel(id=1)
        db.session.add(default_settings)
        db.session.commit()

# Set environment variables with default VM settings
with app.app_context():
    DefaultVmSettingsModel.set_environment_variables_with_defaults()

# Error handlers for 404 and 500 errors
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error/500.html'), 500

# Context processors to inject non-domain and domain model data into templates
@app.context_processor
def inject_non_domain_model_data():
    return {'non_domain_model_data': NonDomainModel.query.all()}

@app.context_processor
def inject_domain_model_data():
    return {'domain_model_data': DomainModel.query.all()}

@app.context_processor
def inject_host_status():
    esxi_ip = get_esxi_ip()
    host_status = is_reachable(esxi_ip)
    return dict(host_status=host_status)

# Set the ESXi host IP address in the database
with app.app_context():
    config = ConfigModel.query.first()
    if config:
        print(f"Starting application..")
    else:
        config = ConfigModel()
        config.set_esxi_ip(os.getenv('ESXI_HOST'))
        db.session.add(config)

    db.session.commit()

# Set up logging
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Custom JSON log formatter
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "level": record.levelname,
            "message": record.getMessage(),
            "user": getattr(record, 'user', 'anonymous'),
            **getattr(record, 'extra', {})
        }
        return json.dumps(log_record)

# Handler for app.log (standard logs)
file_handler = TimedRotatingFileHandler('logs/app.log', when='midnight', interval=1, backupCount=30)
file_handler.suffix = "%Y-%m-%d_%H-%M-%S"
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Handler for app_json.log (JSON logs)
json_file_handler = TimedRotatingFileHandler('logs/app_json.log', when='midnight', interval=1, backupCount=30)
json_file_handler.suffix = "%Y-%m-%d_%H-%M-%S"
json_file_handler.setFormatter(JSONFormatter())
json_file_handler.setLevel(logging.INFO)

# Adding handlers to the Flask app logger
app.logger.addHandler(file_handler)

# Custom JSON logger
json_logger = logging.getLogger('json_logger')
json_logger.setLevel(logging.INFO)
json_logger.addHandler(json_file_handler)

# Custom JSON encoder for logging
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return super().default(obj)

def log_json(level, message, **kwargs):
    log_entry = {
        "level": level,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "user": session.get('username', 'anonymous'),
        "message": message,
        **kwargs
    }
    json_logger.info(json.dumps(log_entry, cls=CustomJSONEncoder))

# Clean up old log files
log_directory = 'logs'
log_retention_days = 30

for log_file in os.listdir(log_directory):
    file_path = os.path.join(log_directory, log_file)
    if os.path.isfile(file_path):
        file_creation_time = os.path.getctime(file_path)
        if (time.time() - file_creation_time) // (24 * 3600) >= log_retention_days:
            os.remove(file_path)
            
if __name__ == "__main__":
    app.run(host='0.0.0.0')
