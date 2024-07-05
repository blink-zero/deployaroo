from apps import db
from sqlalchemy.ext.hybrid import hybrid_property
from apps.models.util import encrypt_password, decrypt_password

class ConfigModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    esxi_ip = db.Column(db.String(15), unique=False)
    vcenter_server = db.Column(db.String(100), default='')
    esxi_host = db.Column(db.String(100), default='')
    vcenter_username = db.Column(db.String(100), default='')
    _vcenter_password = db.Column("vcenter_password", db.String(255), default='')
    discord_webhook_url = db.Column(db.String(255))
    notify_completed = db.Column(db.Boolean, default=False)
    notify_failed = db.Column(db.Boolean, default=False)

    @hybrid_property
    def vcenter_password(self):
        return decrypt_password(self._vcenter_password)

    @vcenter_password.setter
    def vcenter_password(self, value):
        self._vcenter_password = encrypt_password(value)

    def set_esxi_ip(self, esxi_ip):
        self.esxi_ip = esxi_ip

    def set_esxi_host(self, esxi_host):
        self.esxi_host = esxi_host
    
    def set_vcenter_server(self, vcenter_server):
        self.vcenter_server = vcenter_server

    def set_vcenter_username(self, vcenter_username):
        self.vcenter_username = vcenter_username

    def set_vcenter_password(self, vcenter_password):
        self.vcenter_password = vcenter_password

    def get_vcenter_password(self):
        return self.vcenter_password
