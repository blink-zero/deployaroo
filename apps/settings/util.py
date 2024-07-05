from datetime import datetime, timedelta
from flask import current_app
import requests
from apps.models.config_model import ConfigModel
from apps.utils.logging import log_json

def send_discord_notification(message):
    config = ConfigModel.query.first()
    if config and config.discord_webhook_url:
        try:
            payload = {"content": message}
            requests.post(config.discord_webhook_url, json=payload)
            log_json('INFO', 'Discord notification sent', message=message)
        except Exception as e:
            log_json('ERROR', 'Failed to send Discord notification', error=str(e))
            
def model_to_dict(instance):
    return {column.name: getattr(instance, column.name) for column in instance.__table__.columns}
