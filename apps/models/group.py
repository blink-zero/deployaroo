from apps import db

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

    def __init__(self, name, description=None):
        self.name = name
        self.description = description
