import os

# Base configuration class
class Config(object):
    # Secret key for cryptographic operations
    # Randomly generated key, replace with your own key if you are using this in production or Add Environment Variable
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'n73bbeWX2y_oWztEo5ilHyU7D3Im-hjwxgNUvxg1ccc='

    # Encryption key for cryptographic operations relating to password storage
    # Randomly generated key, replace with your own key if you are using this in production or add Environment Variable
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY') or 'n73bbeWX2y_oWztEo5ilHyU7D3Im-hjwxgNUvxg1ccc='
    
    # Database URI, defaulting to SQLite if not provided
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///db.sqlite3'
    
    # Controls SQLAlchemy's modification tracking, set to False for better performance
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Indicates whether session cookies should be sent only over HTTPS
    SESSION_COOKIE_SECURE = True
    
    # Default retention period for logs in days, Currently not used
    LOG_RETENTION_DAYS = 30  
    
    # Default admin user credentials
    APP_ADMIN_USER = os.environ.get('APP_ADMIN_USER', 'admin')
    APP_ADMIN_PASSWORD = os.environ.get('APP_ADMIN_PASSWORD', 'password')

# Configuration class for development environment
class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = False # Need to change this to True when deploying to production but for now we will leave it as False

# Dictionary mapping configuration mode names to their respective configuration classes
config_dict = {
    'Production': ProductionConfig,
    'Debug': DevelopmentConfig
}
