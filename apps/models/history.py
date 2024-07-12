from apps import db
from sqlalchemy.ext.hybrid import hybrid_property
from apps.models.util import encrypt_password, decrypt_password

class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    starttime = db.Column(db.String(15), unique=False, nullable=True)
    endtime = db.Column(db.String(15), unique=False, nullable=True)
    status = db.Column(db.String(15), unique=False, nullable=True)
    ipaddress = db.Column(db.String(15), unique=False, nullable=False)
    hostname = db.Column(db.String(50), unique=False, nullable=False)
    imagetype = db.Column(db.String(50), unique=False, nullable=False)
    machinetype = db.Column(db.String(50), unique=False, nullable=False)
    group = db.Column(db.String(50), unique=False, nullable=False)
    humanname = db.Column(db.String(50), unique=False, nullable=False)
    cpu = db.Column(db.String(50), unique=False, nullable=False)
    ram = db.Column(db.String(50), unique=False, nullable=False)
    env = db.Column(db.String(50), unique=False, nullable=False)
    message_flashed = db.Column(db.Boolean, nullable=False, default=False)
    ansible_log_path = db.Column(db.String(255), unique=False, nullable=True)

    # environment variables
    esxi_host = db.Column(db.String(255), nullable=True)
    vcenter_server = db.Column(db.String(255), nullable=True)
    vcenter_username = db.Column(db.String(255), nullable=True)
    vm_state = db.Column(db.String(50), nullable=True)
    linux_disk_size = db.Column(db.String(50), nullable=True)
    windows_disk_size = db.Column(db.String(50), nullable=True)
    vm_hw_scsi = db.Column(db.String(50), nullable=True)
    vm_type = db.Column(db.String(50), nullable=True)
    timezone = db.Column(db.String(50), nullable=True)
    vm_net_type = db.Column(db.String(50), nullable=True)
    ntp_servers = db.Column(db.String(255), nullable=True)
    ad_upstream_dns1 = db.Column(db.String(50), nullable=True)
    ad_upstream_dns2 = db.Column(db.String(50), nullable=True)
    linux_template_username = db.Column(db.String(50), nullable=True)
    windows_template_username = db.Column(db.String(50), nullable=True)
    temp_ad_domain_name = db.Column(db.String(255), nullable=True)
    designation = db.Column(db.String(50), nullable=True)
    datacenter = db.Column(db.String(255), nullable=True)
    disk_datastore = db.Column(db.String(255), nullable=True)
    vm_network = db.Column(db.String(255), nullable=True)
    subnet_mask = db.Column(db.String(50), nullable=True)
    gateway = db.Column(db.String(50), nullable=True)
    dns_1 = db.Column(db.String(50), nullable=True)
    dns_2 = db.Column(db.String(50), nullable=True)
    vm_folder = db.Column(db.String(255), nullable=True)
    validate_cert = db.Column(db.String(10), nullable=True)
    network_address = db.Column(db.String(50), nullable=True)
    
    # Domain-specific fields
    domain_name = db.Column(db.String(255), nullable=True)
    domain_admin_user = db.Column(db.String(255), nullable=True)
    centos_ou_membership = db.Column(db.String(255), nullable=True)
    ubuntu_ou_membership = db.Column(db.String(255), nullable=True)

    # Sensitive environment variables (encrypted)
    _linux_template_password = db.Column("linux_template_password", db.String(255), nullable=True)
    _windows_template_password = db.Column("windows_template_password", db.String(255), nullable=True)
    _domain_admin_password = db.Column("domain_admin_password", db.String(255), nullable=True)

    @hybrid_property
    def linux_template_password(self):
        return decrypt_password(self._linux_template_password)

    @linux_template_password.setter
    def linux_template_password(self, value):
        self._linux_template_password = encrypt_password(value)

    @hybrid_property
    def windows_template_password(self):
        return decrypt_password(self._windows_template_password)

    @windows_template_password.setter
    def windows_template_password(self, value):
        self._windows_template_password = encrypt_password(value)

    @hybrid_property
    def domain_admin_password(self):
        return decrypt_password(self._domain_admin_password)

    @domain_admin_password.setter
    def domain_admin_password(self, value):
        self._domain_admin_password = encrypt_password(value)

    def __init__(self, starttime, endtime, status, ipaddress, hostname, imagetype, machinetype, group, humanname, cpu, ram, env, ansible_log_path=None, **kwargs):
        self.starttime = starttime
        self.endtime = endtime
        self.status = status
        self.ipaddress = ipaddress
        self.hostname = hostname
        self.imagetype = imagetype
        self.machinetype = machinetype
        self.group = group
        self.humanname = humanname
        self.cpu = cpu
        self.ram = ram
        self.env = env
        self.ansible_log_path = ansible_log_path
        
        # Set environment variable attributes
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)