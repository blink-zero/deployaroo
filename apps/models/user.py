from apps import db, login_manager
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy.orm import relationship

user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    groups = relationship('Group', secondary=user_groups, backref=db.backref('users', lazy='dynamic'))

    def __init__(self, username, password):
        self.username = username
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
