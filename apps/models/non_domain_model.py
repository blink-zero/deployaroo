from apps import db
from sqlalchemy import event, select

class NonDomainModel(db.Model):
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

@event.listens_for(NonDomainModel, 'before_insert')
def generate_nondomain_designation(mapper, connection, target):
    last_designation = connection.scalar(
         select(NonDomainModel.designation).order_by(db.desc(NonDomainModel.id)).limit(1)
    )

    if last_designation:
        new_designation = increment_alphabetic_string(last_designation)
    else:
        new_designation = 'AA'

    target.designation = new_designation

def increment_alphabetic_string(s):
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if len(s) != 2 or s[0] not in alphabet or s[1] not in alphabet:
        raise ValueError("Invalid input string")

    if s[1] == 'Z':
        return alphabet[alphabet.index(s[0]) + 1] + 'A'
    else:
        return s[0] + alphabet[alphabet.index(s[1]) + 1]