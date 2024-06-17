from flask import Blueprint

blueprint = Blueprint(
    'home_blueprint',
    __name__,
    url_prefix=''
)

stream = Blueprint(
    'stream', 
    __name__,
    template_folder='templates'
)
