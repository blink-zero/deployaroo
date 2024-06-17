import os
from apps import db
from sqlalchemy.ext.hybrid import hybrid_property
from apps.models.util import encrypt_password, decrypt_password

class DefaultVmSettingsModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vm_state = db.Column(db.String(100), default='poweredon')
    linux_disk_size = db.Column(db.String(100), default='40')
    windows_disk_size = db.Column(db.String(100), default='100')
    vm_hw_scsi = db.Column(db.String(100), default='paravirtual')
    vm_type = db.Column(db.String(100), default='thin')
    timezone = db.Column(db.String(100), default='255')
    vm_net_type = db.Column(db.String(100), default='vmxnet3')
    ntp_servers = db.Column(db.String(100), default='0.us.pool.ntp.org,1.us.pool.ntp.org,2.us.pool.ntp.org,3.us.pool.ntp.org')
    ad_upstream_dns1 = db.Column(db.String(100), default='8.8.8.8')
    ad_upstream_dns2 = db.Column(db.String(100), default='8.8.4.4')
    linux_template_username = db.Column(db.String(100), default='administrator')
    _linux_template_password = db.Column("linux_template_password", db.String(255), default='')
    windows_template_username = db.Column(db.String(100), default='administrator')
    _windows_template_password = db.Column("windows_template_password", db.String(255), default='')

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

    def set_vm_state(self, vm_state):
        self.vm_state = vm_state

    def set_vm_net_type(self, vm_net_type):
        self.vm_net_type = vm_net_type

    def set_linux_disk_size(self, linux_disk_size):
        self.linux_disk_size = linux_disk_size

    def set_windows_disk_size(self, windows_disk_size):
        self.windows_disk_size = windows_disk_size

    def set_vm_hw_scsi(self, vm_hw_scsi):
        self.vm_hw_scsi = vm_hw_scsi

    def set_vm_type(self, vm_type):
        self.vm_type = vm_type

    def set_timezone(self, timezone):
        self.timezone = timezone

    def set_ntp_servers(self, ntp_servers):
        self.ntp_servers = ntp_servers

    def set_ad_upstream_dns1(self, ad_upstream_dns1):
        self.ad_upstream_dns1 = ad_upstream_dns1

    def set_ad_upstream_dns2(self, ad_upstream_dns2):
        self.ad_upstream_dns2 = ad_upstream_dns2

    def set_linux_template_username(self, linux_template_username):
        self.linux_template_username = linux_template_username

    def set_linux_template_password(self, linux_template_password):
        self.linux_template_password = linux_template_password

    def set_windows_template_username(self, windows_template_username):
        self.windows_template_username = windows_template_username

    def set_windows_template_password(self, windows_template_password):
        self.windows_template_password = windows_template_password

    @classmethod
    def set_environment_variables_with_defaults(cls):
        defaults_instance = cls.query.first()

        if defaults_instance:
            os.environ['VM_STATE'] = defaults_instance.vm_state
            os.environ['VM_NET_TYPE'] = defaults_instance.vm_net_type
            os.environ['LINUX_DISK_SIZE'] = defaults_instance.linux_disk_size
            os.environ['WINDOWS_DISK_SIZE'] = defaults_instance.windows_disk_size
            os.environ['VM_HW_SCSI'] = defaults_instance.vm_hw_scsi
            os.environ['VM_TYPE'] = defaults_instance.vm_type
            os.environ['TIMEZONE'] = defaults_instance.timezone
            os.environ['NTP_SERVERS'] = defaults_instance.ntp_servers
            os.environ['AD_UPSTREAM_DNS1'] = defaults_instance.ad_upstream_dns1
            os.environ['AD_UPSTREAM_DNS2'] = defaults_instance.ad_upstream_dns2
            os.environ['LINUX_TEMPLATE_PASSWORD'] = defaults_instance.linux_template_password
            os.environ['WINDOWS_TEMPLATE_PASSWORD'] = defaults_instance.windows_template_password
            print("Default Environment variables set.")
        else:
            print("No default settings found in the database.")
