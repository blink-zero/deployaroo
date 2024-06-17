from apps import db
from sqlalchemy import event, select
from sqlalchemy.ext.hybrid import hybrid_property
from apps.models.util import decrypt_password, encrypt_password

class DomainModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    designation = db.Column(db.String(2), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    vm_network = db.Column(db.String(100), nullable=False)
    network_address = db.Column(db.String(100), nullable=False)
    subnet_mask = db.Column(db.String(100), nullable=False)
    gateway = db.Column(db.String(100), nullable=False)
    dns_1 = db.Column(db.String(100), nullable=False)
    dns_2 = db.Column(db.String(100), nullable=False)
    validate_cert = db.Column(db.String(100), nullable=False)
    datacenter = db.Column(db.String(100), nullable=False)
    vm_folder = db.Column(db.String(100), nullable=False)
    disk_datastore = db.Column(db.String(100), nullable=False)
    domain_name = db.Column(db.String(100), nullable=False)
    domain_admin_user = db.Column(db.String(100), nullable=False)
    _domain_admin_password = db.Column("domain_admin_password", db.String(255), nullable=False)
    ad_centos_ou_membership = db.Column(db.String(255), nullable=False)
    ad_ubu_ou_membership = db.Column(db.String(255), nullable=False)

    @hybrid_property
    def domain_admin_password(self):
        return decrypt_password(self._domain_admin_password)

    @domain_admin_password.setter
    def domain_admin_password(self, value):
        self._domain_admin_password = encrypt_password(value)

@event.listens_for(DomainModel, 'before_insert')
def generate_domain_designation(mapper, connection, target):
    last_designation = connection.scalar(
        select([DomainModel.designation]).order_by(db.desc(DomainModel.id)).limit(1)
    )

    if last_designation:
        new_designation = increment_alphabetic_string(last_designation)
    else:
        new_designation = 'BA'

    target.designation = new_designation

def increment_alphabetic_string(s):
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if len(s) != 2 or s[0] not in alphabet or s[1] not in alphabet:
        raise ValueError("Invalid input string")

    if s[1] == 'Z':
        return alphabet[alphabet.index(s[0]) + 1] + 'A'
    else:
        return s[0] + alphabet[alphabet.index(s[1]) + 1]
