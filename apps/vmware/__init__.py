from flask import Blueprint

blueprint = Blueprint(
    'vmware_blueprint',
    __name__,
    url_prefix=''
)
