from apps import db

class PluginModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"Plugin(id={self.id}, name={self.name})"
