from datetime import datetime
import logging
import os
import random
import socket
import string
import subprocess
import time
from typing import List
import uuid
from flask import Flask, current_app, session, flash
from apps import db
from apps.config import Config
from apps.models import User, Group, PluginModel, DefaultVmSettingsModel, ConfigModel, History, NonDomainModel, DomainModel
import configparser
import ansible_runner
import yaml
import json
from apps.settings.util import send_discord_notification
from apps.utils.logging import log_json


def model_to_dict(instance):
    return {column.name: getattr(instance, column.name) for column in instance.__table__.columns}

def get_host_status():
    logging.info("Checking host status")
    host_status = is_reachable(get_esxi_ip())
    logging.info(f"Host status: {host_status}")
    return host_status

def get_esxi_ip():
    esxi_ip_env = os.environ.get('ESXI_IP')
    if esxi_ip_env:
        logging.info(f"ESXI IP from environment variable: {esxi_ip_env}")
        return esxi_ip_env

    config = ConfigModel.query.first()
    if config:
        logging.info(f"ESXI IP from database: {config.esxi_ip}")
        return config.esxi_ip
    else:
        logging.warning("ESXI IP not found in environment variables or database")
        return None

def ping_host(host):
    try:
        subprocess.check_output("ping -c 1 -W 2 " + host, shell=True)
        logging.info(f"Host {host} is reachable")
        return True
    except subprocess.CalledProcessError:
        logging.warning(f"Host {host} is not reachable")
        return False

def is_reachable(host, port=443, timeout=1):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        logging.info(f"Host {host} is reachable on port {port}")
        return True
    except Exception as ex:
        logging.error(f"Error reaching host {host} on port {port}: {ex}")
        return False

def get_username():
    user = User.query.get(session['user_id'])
    username = user.username if user else None
    logging.info(f"Retrieved username: {username}")
    return username

def run_playbook_standard(app: Flask, history_id: int, environment, inventory_file):
    pwd = os.getcwd()
    inv_dirname, inv_filename = os.path.split(inventory_file)
    playbook_path = f'{pwd}/{inv_dirname}/{environment}.yml'

    inventory_path = f'{pwd}/{inventory_file}'
    print_inventory(inventory_path)

    with app.app_context():
        history_obj = History.query.get(history_id)
        log_file_path = history_obj.ansible_log_path

        os.environ['ANSIBLE_LOG_PATH'] = log_file_path

        runner = ansible_runner.run(playbook=playbook_path, inventory=inventory_path, envvars={"ANSIBLE_LOG_PATH": log_file_path})

        ansible_status = "Completed" if runner.status == "successful" else "Failed"

        history_obj.status = ansible_status
        history_obj.endtime = time.strftime('%A %B, %d %Y %H:%M:%S')
        db.session.add(history_obj)

        logging.info(f"Updated history {history_obj.id} with status {ansible_status}")

        db.session.commit()

        # Discord notification
        config = ConfigModel.query.first()
        if config:
            if ansible_status == "Completed" and config.notify_completed:
                send_discord_notification(f"Build completed successfully for VM: {history_obj.hostname}")
            elif ansible_status == "Failed" and config.notify_failed:
                send_discord_notification(f"Build failed for VM: {history_obj.hostname}")

    os.remove(inventory_path)
    logging.info(f"Removed Inventory File: {inventory_path}")

# NOT SURE THIS IS NEEDED ANYMORE - DOUBLE CHECK AND DELETE IF NEED BE
def create_inventory_file_environment(ipaddress, hostname, imagetype, machinetype, cpu, ram, group):
    inventory_file = 'apps/plugins/ansible-ad-lab/inventory.yml'

    inventory_data = {}

    try:
        with open(inventory_file, 'r') as file:
            inventory_data = yaml.safe_load(file)
    except FileNotFoundError:
        logging.info(f"Inventory file {inventory_file} not found, creating a new one")

    if 'all' not in inventory_data:
        inventory_data['all'] = {'children': {}}

    if machinetype not in inventory_data['all']['children']:
        inventory_data['all']['children'][machinetype] = {'hosts': {}}

    host_data = {
        'inventory_guest_hostname': hostname,
        'inventory_guest_vcpu': cpu,
        'inventory_guest_vram': ram,
        'inventory_template_name': imagetype,
        'inventory_vm_guestid': group
    }

    inventory_data['all']['children'][machinetype]['hosts'][ipaddress] = host_data

    with open(inventory_file, 'w') as file:
        yaml.dump(inventory_data, file)

    logging.info(f"Created Inventory File for environment: {inventory_file}")

def run_playbook_environment(app: Flask, history_objects: List[History]):
    pwd = os.getcwd()
    playbook_path = f'{pwd}/apps/plugins/ansible-ad-lab/main.yml'

    inventory_path = f'{pwd}/apps/plugins/ansible-ad-lab/inventory.yml'
    print_inventory(inventory_path)

    os.environ['ANSIBLE_LOG_PATH'] = f'{pwd}/logs/app.log'

    runner = ansible_runner.run(playbook=playbook_path, inventory=inventory_path)

    ansible_status = "Completed" if runner.status == "successful" else "Failed"

    os.remove(inventory_path)
    logging.info(f"Removed Inventory File: {inventory_path}")

    with app.app_context():
        for history_obj in history_objects:
            history_obj.status = ansible_status
            history_obj.endtime = time.strftime('%A %B, %d %Y %H:%M:%S')
            db.session.add(history_obj)

            logging.info(f"Updated history {history_obj.id} with status {ansible_status}")

        db.session.commit()

def print_inventory(inventory_path):
    with open(inventory_path, 'r') as file:
        inventory_contents = file.read()
        logging.info(f"Inventory contents: {inventory_contents}")

def get_config(non_domain_item):
    config = {}

    columns = [
        'name', 'vm_network', 'network_address', 'subnet_mask', 'gateway',
        'dns_1', 'dns_2', 'validate_cert', 'datacenter', 'vm_folder', 'disk_datastore'
    ]

    for column in columns:
        var_name = f'{non_domain_item.designation}_{column}'
        config[var_name] = getattr(non_domain_item, column, '')

    return config


def get_config_domain(domain_item):
    config = {}

    columns = [
        'name', 'vm_network', 'network_address', 'subnet_mask', 'gateway',
        'dns_1', 'dns_2', 'validate_cert', 'datacenter', 'vm_folder', 'disk_datastore',
        'domain_name', 'domain_admin_user', 'domain_admin_password'
    ]

    for column in columns:
        var_name = f'{domain_item.designation}_{column.upper()}'
        config[var_name] = getattr(domain_item, column, '')

    return config


def set_environment_variables(config):
    for var_name, var_value in config.items():
        os.environ[var_name.upper()] = var_value

def create_yaml_file_from_designation(designation):
    yaml_file_path = 'apps/plugins/ansible-deploy-vm/vars/other.yml'

    non_domain_item = NonDomainModel.query.filter_by(designation=designation).first()
    config = ConfigModel.query.first()
    default_settings = DefaultVmSettingsModel.query.first()

    if non_domain_item:
        yaml_dict = {
            'vcenter_hostname': f'{{{{ lookup("env", "VCENTER_SERVER") }}}}',
            'vcenter_datacenter': f'{{{{ lookup("env", "{non_domain_item.designation}_DATACENTER") }}}}',
            'vcenter_username': f'{{{{ lookup("env", "VCENTER_USERNAME") }}}}',
            'vcenter_password': f'{{{{ lookup("env", "VCENTER_PASSWORD") }}}}',
            'new_password': f'{{{{ lookup("env", "LINUX_TEMPLATE_PASSWORD") }}}}',
            'timezone': f'{{{{ lookup("env", "TIMEZONE") }}}}',
            'esxi_host': f'{{{{ lookup("env", "ESXI_HOST") }}}}',
            'vm_disk_datastore': f'{{{{ lookup("env", "{non_domain_item.designation}_DISK_DATASTORE") }}}}',
            'lin_disk_size': f'{{{{ lookup("env", "LINUX_DISK_SIZE") }}}}',
            'win_disk_size': f'{{{{ lookup("env", "WINDOWS_DISK_SIZE") }}}}',
            'vm_hw_scsi': f'{{{{ lookup("env", "VM_HW_SCSI") }}}}',
            'vm_state': f'{{{{ lookup("env", "VM_STATE") }}}}',
            'vm_net_name': f'{{{{ lookup("env", "{non_domain_item.designation}_VM_NETWORK") }}}}',
            'vm_net_type': f'{{{{ lookup("env", "VM_NET_TYPE") }}}}',
            'netmask': f'{{{{ lookup("env", "{non_domain_item.designation}_SUBNET_MASK") }}}}',
            'gateway': f'{{{{ lookup("env", "{non_domain_item.designation}_GATEWAY") }}}}',
            'dns1': f'{{{{ lookup("env", "{non_domain_item.designation}_DNS_1") }}}}',
            'dns2': f'{{{{ lookup("env", "{non_domain_item.designation}_DNS_2") }}}}',
            'vm_folder': f'{{{{ lookup("env", "{non_domain_item.designation}_VM_FOLDER") }}}}',
            'vcenter_validate_certs': f'{{{{ lookup("env", "{non_domain_item.designation}_VALIDATE_CERT") }}}}',
            'linux_template_username': f'{{{{ lookup("env", "LINUX_TEMPLATE_USERNAME") }}}}',
            'linux_template_password': f'{{{{ lookup("env", "LINUX_TEMPLATE_PASSWORD") }}}}',
            'windows_template_password': f'{{{{ lookup("env", "WINDOWS_TEMPLATE_PASSWORD") }}}}',
            'windows_template_username': f'{{{{ lookup("env", "WINDOWS_TEMPLATE_USERNAME") }}}}',
            'ntp_servers': f'{{{{ lookup("env", "NTP_SERVERS") }}}}',
            'vm_type': f'{{{{ lookup("env", "VM_TYPE") }}}}',
            'network_address': f'{{{{ lookup("env", "{non_domain_item.designation}_NETWORK_ADDRESS") }}}}',
            # Used only for the ad domain controller build
            'temp_ad_domain_name': f'{{{{ lookup("env", "TEMP_AD_DOMAIN_NAME") }}}}',
        }

        yaml_contents = yaml.dump(yaml_dict, default_flow_style=False)

        with open(yaml_file_path, 'w') as yaml_file:
            yaml.dump(yaml_dict, yaml_file, default_flow_style=False)

        logging.info(f"Created YAML file from designation: {yaml_file_path}")
        log_json("INFO", "Created YAML file from designation", designation=designation, yaml_contents=yaml_contents)

        return yaml_file_path
    else:
        logging.warning(f"No NonDomainModel found for designation: {designation}")
        log_json("WARNING", "No NonDomainModel found for designation", designation=designation)
        return None

def create_yaml_file_from_designation_domain(designation):
    yaml_file_path = 'apps/plugins/ansible-deploy-vm-domain/vars/other.yml'

    domain_item = DomainModel.query.filter_by(designation=designation).first()
    config = ConfigModel.query.first()
    default_settings = DefaultVmSettingsModel.query.first()

    if domain_item:
        yaml_dict = {
            'vcenter_hostname': f'{{{{ lookup("env", "VCENTER_SERVER") }}}}',
            'vcenter_datacenter': f'{{{{ lookup("env", "{domain_item.designation}_DATACENTER") }}}}',
            'vcenter_username': f'{{{{ lookup("env", "VCENTER_USERNAME") }}}}',
            'vcenter_password': f'{{{{ lookup("env", "VCENTER_PASSWORD") }}}}',
          #  'new_password': f'{{{{ lookup("env", "LINUX_TEMPLATE_PASSWORD") }}}}',
          #  'lin_password': f'{{{{ lookup("env", "LINUX_TEMPLATE_PASSWORD") }}}}',
            'domain_join_username': f'{{{{ lookup("env", "{domain_item.designation}_DOMAIN_ADMIN_USER") }}}}',
            'domain_join_password': f'{{{{ lookup("env", "{domain_item.designation}_DOMAIN_ADMIN_PASSWORD") }}}}',
            'timezone': f'{{{{ lookup("env", "TIMEZONE") }}}}',
            'esxi_host': f'{{{{ lookup("env", "ESXI_HOST") }}}}',
            'vm_disk_datastore': f'{{{{ lookup("env", "{domain_item.designation}_DISK_DATASTORE") }}}}',
            'lin_disk_size': f'{{{{ lookup("env", "LINUX_DISK_SIZE") }}}}',
            'win_disk_size': f'{{{{ lookup("env", "WINDOWS_DISK_SIZE") }}}}',
            'vm_hw_scsi': f'{{{{ lookup("env", "VM_HW_SCSI") }}}}',
            'vm_state': f'{{{{ lookup("env", "VM_STATE") }}}}',
            'vm_net_name': f'{{{{ lookup("env", "{domain_item.designation}_VM_NETWORK") }}}}',
            'vm_net_type': f'{{{{ lookup("env", "VM_NET_TYPE") }}}}',
            'netmask': f'{{{{ lookup("env", "{domain_item.designation}_SUBNET_MASK") }}}}',
            'gateway': f'{{{{ lookup("env", "{domain_item.designation}_GATEWAY") }}}}',
            'dns1': f'{{{{ lookup("env", "{domain_item.designation}_DNS_1") }}}}',
            'dns2': f'{{{{ lookup("env", "{domain_item.designation}_DNS_2") }}}}',
            'vm_folder': f'{{{{ lookup("env", "{domain_item.designation}_VM_FOLDER") }}}}',
            'ad_domain': f'{{{{ lookup("env", "{domain_item.designation}_DOMAIN_NAME") }}}}',
           # 'lin_username': f'{{{{ lookup("env", "COMMON_LINUX_ADMIN_USER") }}}}',
            'ad_centos_ou_membership': f'{{{{ lookup("env", "{domain_item.designation}_CENTOS_OU_MEMBERSHIP") }}}}',
            'ad_ubu_ou_membership': f'{{{{ lookup("env", "{domain_item.designation}_UBUNTU_OU_MEMBERSHIP") }}}}',
            'vcenter_validate_certs': f'{{{{ lookup("env", "{domain_item.designation}_VALIDATE_CERT") }}}}',
            'vm_type': f'{{{{ lookup("env", "VM_TYPE") }}}}',
            'linux_template_username': f'{{{{ lookup("env", "LINUX_TEMPLATE_USERNAME") }}}}',
            'linux_template_password': f'{{{{ lookup("env", "LINUX_TEMPLATE_PASSWORD") }}}}',
            'windows_template_password': f'{{{{ lookup("env", "WINDOWS_TEMPLATE_PASSWORD") }}}}',
        }

        yaml_contents = yaml.dump(yaml_dict, default_flow_style=False)

        with open(yaml_file_path, 'w') as yaml_file:
            yaml.dump(yaml_dict, yaml_file, default_flow_style=False)

        logging.info(f"Created YAML file from designation: {yaml_file_path}")
        log_json("INFO", "Created YAML file from designation", designation=designation, yaml_contents=yaml_contents)

        return yaml_file_path
    else:
        logging.warning(f"No DomainModel found for designation: {designation}")
        log_json("WARNING", "No DomainModel found for designation", designation=designation)
        return None
    

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for i in range(length))

