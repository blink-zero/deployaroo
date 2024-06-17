from datetime import datetime, timedelta
from flask import current_app

def model_to_dict(instance):
    return {column.name: getattr(instance, column.name) for column in instance.__table__.columns}
