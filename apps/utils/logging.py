import json
from datetime import datetime
import logging
from flask import session

# Custom JSON encoder for logging
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return super().default(obj)

# Custom JSON log formatter
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "level": record.levelname,
            "message": record.msg,
            "user": getattr(record, 'user', 'anonymous'),
            **getattr(record, 'extra', {})
        }
        return json.dumps(log_record, cls=CustomJSONEncoder)

def log_json(level, message, **kwargs):
    json_logger = logging.getLogger('json_logger')
    extra_info = {"extra": kwargs, "user": session.get('username', 'anonymous')}
    json_logger.log(getattr(logging, level), message, extra=extra_info)
