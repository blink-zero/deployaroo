from apps import db

class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    starttime = db.Column(db.String(15), unique=False, nullable=True)
    endtime = db.Column(db.String(15), unique=False, nullable=True)
    status = db.Column(db.String(15), unique=False, nullable=True)
    ipaddress = db.Column(db.String(15), unique=False, nullable=False)
    hostname = db.Column(db.String(50), unique=False, nullable=False)
    imagetype = db.Column(db.String(50), unique=False, nullable=False)
    cpu = db.Column(db.String(50), unique=False, nullable=False)
    ram = db.Column(db.String(50), unique=False, nullable=False)
    env = db.Column(db.String(50), unique=False, nullable=False)
    message_flashed = db.Column(db.Boolean, nullable=False, default=False)
    ansible_log_path = db.Column(db.String(255), unique=False, nullable=True)

    def __init__(self, starttime, endtime, status, ipaddress, hostname, imagetype, cpu, ram, env, ansible_log_path=None):
        self.starttime = starttime
        self.endtime = endtime
        self.status = status
        self.ipaddress = ipaddress
        self.hostname = hostname
        self.imagetype = imagetype
        self.cpu = cpu
        self.ram = ram
        self.env = env
        self.ansible_log_path = ansible_log_path
