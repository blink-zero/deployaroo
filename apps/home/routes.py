from io import BytesIO, StringIO
import ssl
from flask import make_response, stream_with_context
from apps.settings.util import send_discord_notification
from apps.vmware.routes import get_vm_by_name, get_vmware_connection
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, Spacer
import csv
import os
import time
import json
import logging
import threading
from datetime import datetime, timedelta
import yaml
import markdown
import requests
import urllib.request
import base64
import asyncio
import subprocess
from functools import wraps
from flask import (
    Blueprint, current_app, jsonify, render_template, redirect, 
    request, session, url_for, send_file, abort, flash, Response
)
from flask_login import login_required, current_user
from flask_paginate import Pagination, get_page_parameter
from werkzeug.security import generate_password_hash
from apps.config import Config
from apps.home import blueprint, stream
from apps.models import (
    User, Group, PluginModel, DefaultVmSettingsModel, ConfigModel, 
    History, NonDomainModel, DomainModel
)
from apps.home.util import (
    create_yaml_file_from_designation, create_yaml_file_from_designation_domain, 
    get_config_domain, get_host_status, get_esxi_ip,
    is_reachable, run_playbook_standard, create_inventory_file_environment, 
    run_playbook_environment, get_config, set_environment_variables
)
from apps import db
import uuid

from apps.models.vm_image_model import VmImageModel
from apps.utils.logging import log_json
from pyVim import connect
from pyVmomi import vim
import paramiko
from sqlalchemy.exc import SQLAlchemyError
import winrm

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or 1 not in [group.id for group in current_user.groups]:
            return render_template('error/403.html'), 403
        return func(*args, **kwargs)
    return decorated_view

@blueprint.context_processor
def inject_non_domain_model_data():
    return {'non_domain_model_data': NonDomainModel.query.all()}

@blueprint.context_processor
def inject_domain_model_data():
    return {'domain_model_data': DomainModel.query.all()}

@blueprint.route('/host_status')
def get_host_status_route():
    host_status = get_host_status()
    return jsonify({'host_status': host_status})

@blueprint.route('/running_vms')
@login_required
def running_vms():
    running_vms_count = History.query.filter(History.status == 'Running').count()
    return jsonify({'running_vms_count': running_vms_count})

@blueprint.route('/documentation')
@login_required
def documentation():
    log_json('INFO', 'Accessed documentation page')
    pwd = os.getcwd()
    with open(f'{pwd}/apps/templates/home/documentation.md', 'r') as file:
        content = file.read()
    html_content = markdown.markdown(content)
    return render_template('home/documentation.html', content=html_content)

@blueprint.route('/logs')
@login_required
def logs():
    log_json('INFO', 'Accessed logs page')
    return render_template('home/logs.html')

@blueprint.route('/download/server_log')
@login_required
def download_log():
    log_json('INFO', 'Downloaded logs file')
    pwd = os.getcwd()
    filepath = f'{pwd}/logs/app_json.log'

    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name='app_json.log')
    else:
        log_json('ERROR', 'Log file not found', path=filepath)
        abort(404)

@blueprint.route('/home')
@login_required
def home():
    if not current_user.is_authenticated:
        return redirect(url_for('auth_blueprint.login'))

    log_json('INFO', 'Accessed home page')
    vmcount = History.query.filter(History.status == 'Completed').count()
    data = History.query.order_by(History.id.desc()).limit(5).all()
    data2 = History.query.order_by(History.id.desc()).all()
    errorcount = History.query.filter(History.status == 'Failed').count()
    vmrunning = History.query.filter(History.status == 'Running').count()
    allevents = History.query.count()
    host_status = is_reachable(get_esxi_ip())
    esxi_ip = get_esxi_ip()

    unflashed_histories = History.query.filter(History.message_flashed == False).order_by(History.id.desc()).all()

    for history in unflashed_histories:
        if history.status != "Running":
            if history.status == "Completed":
                flash(f'{history.hostname} Created.', 'success')
            else:
                flash(f'{history.hostname} Failed.', 'error')

            history.message_flashed = True
            db.session.commit()

    plugins = PluginModel.query.all()

    build_times = History.query.filter(History.status == 'Completed').all()
    total_time = sum(
        (datetime.strptime(event.endtime, '%A %B, %d %Y %H:%M:%S') - datetime.strptime(event.starttime, '%A %B, %d %Y %H:%M:%S')).total_seconds()
        for event in build_times if event.endtime and event.starttime
    )
    average_build_time = total_time / len(build_times) if build_times else 0
    average_build_time = f"{average_build_time / 60:.2f} minutes"

    app_start_time = datetime.strptime(os.getenv('APP_START_TIME', datetime.now().strftime('%Y-%m-%d %H:%M:%S')), '%Y-%m-%d %H:%M:%S')
    system_uptime = (datetime.now() - app_start_time).days

    performance_score = round((vmcount / allevents) * 100) if allevents else 100

    return render_template(
        'home/index.html',
        vmcount=vmcount,
        data=data,
        data2=data2,
        errorcount=errorcount,
        vmrunning=vmrunning,
        allevents=allevents,
        plugins=plugins,
        averageBuildTime=average_build_time,
        systemUptime=system_uptime,
        performanceScore=performance_score,
        esxi_ip=esxi_ip,
        vmrunning_count=vmrunning
    )

@blueprint.route('/history')
@login_required
def history():
    log_json('INFO', 'Accessed history page')

    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 12
    search_query = request.args.get('search', '')
    sort_column = request.args.get('sort', 'id')
    sort_order = request.args.get('order', 'desc')

    log_json('INFO', 'History search', search_query=search_query, sort_column=sort_column, sort_order=sort_order)

    data_query = History.query

    if search_query:
        data_query = data_query.filter(
            History.hostname.ilike(f'%{search_query}%') | 
            History.ipaddress.ilike(f'%{search_query}%') | 
            History.imagetype.ilike(f'%{search_query}%') | 
            History.env.ilike(f'%{search_query}%') |
            History.status.ilike(f'%{search_query}%')
        )

    if sort_column == 'time_taken':
        if sort_order == 'asc':
            data_query = data_query.order_by(History.endtime.asc(), History.starttime.asc())
        else:
            data_query = data_query.order_by(History.endtime.desc(), History.starttime.desc())
    else:
        if sort_order == 'asc':
            data_query = data_query.order_by(getattr(History, sort_column).asc())
        else:
            data_query = data_query.order_by(getattr(History, sort_column).desc())

    unflashed_histories = History.query.filter(History.message_flashed == False).order_by(History.id.desc()).all()

    for history in unflashed_histories:
        if history.status != "Running":
            if history.status == "Completed":
                flash(f'{ history.hostname } Created.', 'success')
            else:
                flash(f'{ history.hostname } Failed.', 'error')

            history.message_flashed = True
            db.session.commit()

    total = data_query.count()
    data = data_query.paginate(page=page, per_page=per_page)
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap4')

    for row in data.items:
        try:
            start_time = datetime.strptime(row.starttime, '%A %B, %d %Y %H:%M:%S')
            end_time = datetime.strptime(row.endtime, '%A %B, %d %Y %H:%M:%S') if row.endtime and row.endtime != "In Progress" else None
            row.time_taken = (end_time - start_time) if end_time else None
            row.formatted_starttime = start_time.strftime('%m/%d/%Y %H:%M')
            row.formatted_endtime = end_time.strftime('%m/%d/%Y %H:%M') if end_time else "In Progress"
        except ValueError as e:
            log_json('ERROR', 'Datetime conversion error', row_id=row.id, error=str(e))
            row.time_taken = None

    return render_template('home/history.html', data=data, pagination=pagination, search_query=search_query, sort_column=sort_column, sort_order=sort_order)



@blueprint.route('/restart_vm/<int:vm_id>', methods=['POST'])
@login_required
@admin_required
def restart_vm(vm_id):
    try:
        vm_record = History.query.get(vm_id)
        if not vm_record:
            log_json('ERROR', f'VM not found in database for ID: {vm_id}')
            return jsonify({'success': False, 'message': 'VM not found in database.'}), 404

        si = get_vmware_connection()
        content = si.RetrieveContent()
        vm = get_vm_by_name(content, vm_record.hostname)

        if not vm:
            log_json('ERROR', f'VM not found in VMware: {vm_record.hostname}')
            return jsonify({'success': False, 'message': 'VM not found in VMware.'}), 404

        if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOff:
            task = vm.PowerOn()
        else:
            task = vm.ResetVM_Task()

        log_json('INFO', f'VM restart initiated for VM: {vm_record.hostname}')
        return jsonify({'success': True, 'message': 'VM restart initiated successfully.'})
    except Exception as e:
        log_json('ERROR', f'Failed to restart VM ID: {vm_id}', error=str(e))
        return jsonify({'success': False, 'message': f'Failed to restart VM: {str(e)}'}), 500
    finally:
        if 'si' in locals():
            connect.Disconnect(si)

@blueprint.route('/vm_details/<int:vm_id>')
@login_required
@admin_required
def vm_details(vm_id):
    try:
        vm = History.query.get(vm_id)
        if vm:

            # ref: https://docs.vmware.com/en/VMware-HCX/4.9/hcx-user-guide/GUID-D4FFCBD6-9FEC-44E5-9E26-1BD0A2A81389.html

            windows_groups = [
                'win31Guest', 'win95Guest', 'win98Guest', 'winntGuest', 'win2000ProGuest',
                'win2000ServGuest', 'win2000AdvServGuest', 'winXPProGuest', 'winXPPro64Guest',
                'winNetEnterpriseGuest', 'winNetDatacenterGuest', 'winNetStandardGuest',
                'winNetWebGuest', 'winNetBusinessGuest', 'winNetEnterprise64Guest',
                'winNetDatacenter64Guest', 'winNetStandard64Guest', 'winVistaGuest',
                'winVista64Guest', 'winLonghornGuest', 'winLonghorn64Guest', 'windows7Guest',
                'windows7_64Guest', 'windows7Server64Guest', 'windows8Guest', 'windows8_64Guest',
                'windows8Server64Guest', 'windows9Guest', 'windows9_64Guest',
                'windows9Server64Guest', 'windows2019srv_64Guest'
            ]

            is_windows = vm.group in windows_groups

            details = {
                'humanname': vm.humanname,
                'hostname': vm.hostname,
                'ipaddress': vm.ipaddress,
                'imagetype': vm.imagetype,
                'group': vm.group,
                'designation': vm.designation,
                'env': vm.env,
                'cpu': vm.cpu,
                'ram': vm.ram,
                'status': vm.status,
                'starttime': vm.starttime,
                'endtime': vm.endtime,
                'vm_state': vm.vm_state,
                'disk_size': vm.windows_disk_size if is_windows else vm.linux_disk_size,
                'vm_network': vm.vm_network,
                'subnet_mask': vm.subnet_mask,
                'gateway': vm.gateway,
                'dns_1': vm.dns_1,
                'dns_2': vm.dns_2,
                'vm_folder': vm.vm_folder,
                'datacenter': vm.datacenter,
                'disk_datastore': vm.disk_datastore,
                'windows_template_username': vm.windows_template_username,
                'linux_template_username': vm.linux_template_username,
                'domain_name': vm.domain_name if hasattr(vm, 'domain_name') else None,
                'domain_admin_user': vm.domain_admin_user if hasattr(vm, 'domain_admin_user') else None,
                'centos_ou_membership': vm.centos_ou_membership if hasattr(vm, 'centos_ou_membership') else None,
                'ubuntu_ou_membership': vm.ubuntu_ou_membership if hasattr(vm, 'ubuntu_ou_membership') else None,
            }
            log_json('INFO', f'VM details retrieved for VM ID: {vm_id}')
            return jsonify(details)
        else:
            log_json('ERROR', f'VM not found for ID: {vm_id}')
            return jsonify({'error': 'VM not found'}), 404
    except Exception as e:
        log_json('ERROR', f'Error fetching VM details for VM ID: {vm_id}', error=str(e))
        return jsonify({'error': 'Failed to fetch VM details'}), 500

def handle_item_id(environment, item_id):
    if environment == 'other' and item_id:
        item = NonDomainModel.query.get(item_id)
        if item:
            config = get_config(item)
            set_environment_variables(config)
            environment_name = item.name
            yaml_file_path = create_yaml_file_from_designation(item.designation)
            log_json('INFO', 'YAML file created from designation', yaml_file_path=yaml_file_path)
            return environment_name, 'ansible-deploy-vm'

    elif environment == 'other_domain' and item_id:
        item = DomainModel.query.get(item_id)
        if item:
            config = get_config_domain(item)
            set_environment_variables(config)
            environment_name = item.name
            yaml_file_path = create_yaml_file_from_designation_domain(item.designation)
            log_json('INFO', 'YAML file created from designation', yaml_file_path=yaml_file_path)
            return environment_name, 'ansible-deploy-vm-domain'

    return None, 'ansible-deploy-vm'

@blueprint.route('/create_machine/<environment>', methods=['POST'])
@login_required
@admin_required
def create_machine(environment):
    environment_name = 'OTHER'
    playbook_location = 'ansible-deploy-vm'

    log_json('INFO', 'Create machine request received', environment=environment, environment_name=environment_name)

    item_id = request.form.get('item_id')

    # Explicitly check for domain and non-domain items
    domain_item = None
    non_domain_item = None
    if environment == 'other_domain':
        domain_item = DomainModel.query.get(item_id)
        if domain_item:
            environment_name = domain_item.name
            playbook_location = 'ansible-deploy-vm-domain'
    elif environment == 'other':
        non_domain_item = NonDomainModel.query.get(item_id)
        if non_domain_item:
            environment_name = non_domain_item.name

    item_environment_name, item_playbook_location = handle_item_id(environment, item_id)
    
    environment_name = item_environment_name or environment_name
    playbook_location = item_playbook_location or playbook_location

    # domain_item = DomainModel.query.get(item_id)
    # non_domain_item = NonDomainModel.query.get(item_id)
    config = ConfigModel.query.first()
    default_settings = DefaultVmSettingsModel.query.first()

    if config:
        os.environ['ESXI_HOST'] = config.esxi_host
        os.environ['VCENTER_SERVER'] = config.vcenter_server
        os.environ['VCENTER_USERNAME'] = config.vcenter_username
        os.environ['VCENTER_PASSWORD'] = config.vcenter_password

    if default_settings:
        os.environ['VM_STATE'] = default_settings.vm_state
        os.environ['LINUX_DISK_SIZE'] = default_settings.linux_disk_size
        os.environ['WINDOWS_DISK_SIZE'] = default_settings.windows_disk_size
        os.environ['VM_HW_SCSI'] = default_settings.vm_hw_scsi
        os.environ['VM_TYPE'] = default_settings.vm_type
        os.environ['TIMEZONE'] = default_settings.timezone
        os.environ['VM_NET_TYPE'] = default_settings.vm_net_type
        os.environ['NTP_SERVERS'] = default_settings.ntp_servers
        os.environ['AD_UPSTREAM_DNS1'] = default_settings.ad_upstream_dns1
        os.environ['AD_UPSTREAM_DNS2'] = default_settings.ad_upstream_dns2
        os.environ['LINUX_TEMPLATE_USERNAME'] = default_settings.linux_template_username
        os.environ['LINUX_TEMPLATE_PASSWORD'] = default_settings.linux_template_password
        os.environ['WINDOWS_TEMPLATE_USERNAME'] = default_settings.windows_template_username
        os.environ['WINDOWS_TEMPLATE_PASSWORD'] = default_settings.windows_template_password

    if domain_item:
        set_environment_variables_from_item(domain_item)
    elif non_domain_item:
        set_environment_variables_from_item(non_domain_item)

    domain_name = request.form.get('domain_name')
    if domain_name:
        os.environ['TEMP_AD_DOMAIN_NAME'] = domain_name

    client_machines = request.form.get('client_machines')
    if client_machines:
        client_machines = json.loads(client_machines)
    else:
        client_machines = [{
            'ipaddress': request.form.get('ipaddress'),
            'hostname': request.form.get('hostname'),
            'imagetype': request.form.get('imagetype').split('|')[0],
            'machinetype': request.form.get('imagetype').split('|')[1],
            'group': request.form.get('imagetype').split('|')[2],
            'humanname': request.form.get('imagetype').split('|')[3],
            'cpu': request.form.get('cpu'),
            'ram': request.form.get('ram'),
        }]

    for client_machine in client_machines:
        ipaddress = client_machine['ipaddress']
        hostname = client_machine['hostname']
        imagetype = client_machine['imagetype']
        machinetype = client_machine['machinetype']
        group = client_machine['group']
        humanname = client_machine['humanname']
        cpu = client_machine['cpu']
        ram = client_machine['ram']

        timestamp = time.strftime('%Y%m%d%H%M%S')
        log_file_name = f"{timestamp}_{hostname}.log"
        pwd = os.getcwd()
        ansible_log_path = os.path.join(f'{pwd}/logs/build_logs', log_file_name)

        item = domain_item or non_domain_item  # Use whichever is not None
        if item:
            designation = item.designation
        else:
            designation = ''

        # Common environment variables
        common_env_vars = {
            'esxi_host': os.environ.get('ESXI_HOST'),
            'vcenter_server': os.environ.get('VCENTER_SERVER'),
            'vcenter_username': os.environ.get('VCENTER_USERNAME'),
            'vm_state': os.environ.get('VM_STATE'),
            'linux_disk_size': os.environ.get('LINUX_DISK_SIZE'),
            'windows_disk_size': os.environ.get('WINDOWS_DISK_SIZE'),
            'vm_hw_scsi': os.environ.get('VM_HW_SCSI'),
            'vm_type': os.environ.get('VM_TYPE'),
            'timezone': os.environ.get('TIMEZONE'),
            'vm_net_type': os.environ.get('VM_NET_TYPE'),
            'ntp_servers': os.environ.get('NTP_SERVERS'),
            'ad_upstream_dns1': os.environ.get('AD_UPSTREAM_DNS1'),
            'ad_upstream_dns2': os.environ.get('AD_UPSTREAM_DNS2'),
            'linux_template_username': os.environ.get('LINUX_TEMPLATE_USERNAME'),
            'linux_template_password': os.environ.get('LINUX_TEMPLATE_PASSWORD'),
            'windows_template_username': os.environ.get('WINDOWS_TEMPLATE_USERNAME'),
            'windows_template_password': os.environ.get('WINDOWS_TEMPLATE_PASSWORD'),
            'designation': designation,
            'datacenter': os.environ.get(f'{designation}_DATACENTER'),
            'disk_datastore': os.environ.get(f'{designation}_DISK_DATASTORE'),
            'vm_network': os.environ.get(f'{designation}_VM_NETWORK'),
            'subnet_mask': os.environ.get(f'{designation}_SUBNET_MASK'),
            'gateway': os.environ.get(f'{designation}_GATEWAY'),
            'dns_1': os.environ.get(f'{designation}_DNS_1'),
            'dns_2': os.environ.get(f'{designation}_DNS_2'),
            'vm_folder': os.environ.get(f'{designation}_VM_FOLDER'),
            'validate_cert': os.environ.get(f'{designation}_VALIDATE_CERT'),
            'network_address': os.environ.get(f'{designation}_NETWORK_ADDRESS'),
        }

        # Domain-specific environment variables
        domain_env_vars = {
            'temp_ad_domain_name': os.environ.get('TEMP_AD_DOMAIN_NAME'),
            'domain_name': os.environ.get(f'{designation}_DOMAIN_NAME'),
            'domain_admin_user': os.environ.get(f'{designation}_DOMAIN_ADMIN_USER'),
            'domain_admin_password': os.environ.get(f'{designation}_DOMAIN_ADMIN_PASSWORD'),
            'centos_ou_membership': os.environ.get(f'{designation}_CENTOS_OU_MEMBERSHIP'),
            'ubuntu_ou_membership': os.environ.get(f'{designation}_UBUNTU_OU_MEMBERSHIP')
        }

        # Combine common and domain-specific vars only if it's a domain machine
        if domain_item:
            env_vars = {**common_env_vars, **domain_env_vars}
        else:
            env_vars = common_env_vars

        new_history = History(
            starttime=time.strftime('%A %B, %d %Y %H:%M:%S'),
            endtime="In Progress",
            status="Running",
            ipaddress=ipaddress,
            hostname=hostname,
            imagetype=imagetype,
            machinetype=machinetype,
            group=group,
            humanname=humanname,
            cpu=cpu,
            ram=ram,
            env=environment_name,
            ansible_log_path=ansible_log_path,
            **env_vars
        )

        db.session.add(new_history)
        db.session.commit()

        log_json('INFO', 'New history entry created', history_id=new_history.id, hostname=hostname)
        flash(f'Job Running: {hostname}', 'warning')

        inventory_data = {
            'all': {
                'children': {
                    machinetype: {
                        'hosts': {
                            ipaddress: {
                                'guest_hostname': hostname,
                                'guest_vcpu': cpu,
                                'guest_vram': ram,
                                'template_name': imagetype,
                                'vm_guestid': group
                            }
                        }
                    }
                }
            }
        }

        inventory_file = f'apps/plugins/{playbook_location}/inventory_{str(uuid.uuid4())}.yml'
        with open(inventory_file, 'w') as file:
            yaml.dump(inventory_data, file)

        logging.info(f"Created Inventory File: {inventory_file}")
        log_json('INFO', f'Inventory file created for VM {hostname} ({ipaddress})', inventory_file=inventory_file, yaml_contents=yaml.dump(inventory_data, default_flow_style=False))

        app = current_app._get_current_object()

        playbook_thread = threading.Thread(
            target=run_playbook_standard, args=(app, new_history.id, environment, inventory_file))
        playbook_thread.start()

    log_json('INFO', 'Playbook execution started', environment=environment)

    config = ConfigModel.query.first()
    if config:
        for client_machine in client_machines:
            hostname = client_machine['hostname']
            if config.notify_completed:
                send_discord_notification(f"Build started for VM: {hostname}")

    return redirect('/home')


def set_environment_variables_from_item(item):
    os.environ[f'{item.designation}_DATACENTER'] = item.datacenter
    os.environ[f'{item.designation}_DISK_DATASTORE'] = item.disk_datastore
    os.environ[f'{item.designation}_VM_NETWORK'] = item.vm_network
    os.environ[f'{item.designation}_SUBNET_MASK'] = item.subnet_mask
    os.environ[f'{item.designation}_GATEWAY'] = item.gateway
    os.environ[f'{item.designation}_DNS_1'] = item.dns_1
    os.environ[f'{item.designation}_DNS_2'] = item.dns_2
    os.environ[f'{item.designation}_VM_FOLDER'] = item.vm_folder
    os.environ[f'{item.designation}_VALIDATE_CERT'] = item.validate_cert
    os.environ[f'{item.designation}_NETWORK_ADDRESS'] = item.network_address
    if isinstance(item, DomainModel):
        os.environ[f'{item.designation}_DOMAIN_NAME'] = item.domain_name
        os.environ[f'{item.designation}_DOMAIN_ADMIN_USER'] = item.domain_admin_user
        os.environ[f'{item.designation}_DOMAIN_ADMIN_PASSWORD'] = item.domain_admin_password
        os.environ[f'{item.designation}_CENTOS_OU_MEMBERSHIP'] = item.ad_centos_ou_membership
        os.environ[f'{item.designation}_UBUNTU_OU_MEMBERSHIP'] = item.ad_ubu_ou_membership

@blueprint.route('/submit_machines', methods=['POST'])
@login_required
@admin_required
def submit_machines():
    log_json('INFO', 'Submit machines request received')
    server_machines = request.form.get('server_machines')
    client_machines = request.form.get('client_machines')

    server_machines = json.loads(server_machines)
    client_machines = json.loads(client_machines)

    history_objects = []

    for server_machine in server_machines:
        ipaddress = server_machine['ipaddress']
        hostname = server_machine['hostname']
        imagetype = server_machine['imagetype']
        machinetype = server_machine['machinetype']
        group = server_machine['group']
        cpu = server_machine['cpu']
        ram = server_machine['ram']

        create_inventory_file_environment(
            ipaddress, hostname, imagetype, machinetype, cpu, ram, group)
        new_history = History(
            starttime=time.strftime('%A %B, %d %Y %H:%M:%S'),
            endtime="In Progress", status="Running",
            ipaddress=ipaddress, hostname=hostname, imagetype=imagetype,
            cpu=cpu, ram=ram, env="NEW ENVIRONMENT"
        )
        db.session.add(new_history)
        db.session.commit()

        history_objects.append(new_history)
        flash(f'Job Running: {hostname}', 'warning')

    for client_machine in client_machines:
        ipaddress = client_machine['ipaddress']
        hostname = client_machine['hostname']
        imagetype = client_machine['imagetype']
        machinetype = client_machine['machinetype']
        group = client_machine['group']
        cpu = client_machine['cpu']
        ram = client_machine['ram']

        create_inventory_file_environment(
            ipaddress, hostname, imagetype, machinetype, cpu, ram, group)
        new_history = History(
            starttime=time.strftime('%A %B, %d %Y %H:%M:%S'),
            endtime="In Progress", status="Running",
            ipaddress=ipaddress, hostname=hostname, imagetype=imagetype,
            cpu=cpu, ram=ram, env="NEW ENVIRONMENT"
        )
        db.session.add(new_history)
        db.session.commit()

        history_objects.append(new_history)
        flash(f'Job Running: {hostname}', 'warning')

    app = current_app._get_current_object()
    playbook_thread = threading.Thread(
        target=run_playbook_environment, args=(app, history_objects,))
    playbook_thread.start()

    log_json('INFO', 'Submit machines playbook execution started', server_machines=server_machines, client_machines=client_machines)
    return jsonify({'redirect': url_for('home_blueprint.home')})

@blueprint.route('/ansible-deploy-vm/<playbook_name>')
@login_required
@admin_required
def serve_playbook(playbook_name):
    log_json('INFO', 'Serve playbook request received', playbook_name=playbook_name)
    with open('../ansible-deploy-vm/' + playbook_name, 'r') as f:
        playbook_content = f.read()
    return playbook_content

@blueprint.route('/add_network_nondomain', methods=['GET', 'POST'])
@login_required
@admin_required
def add_network_nondomain():
    log_json('INFO', 'Accessed add network non-domain route')
    config = ConfigModel.query.get(1)

    vcenter_config = bool(config and config.vcenter_server and config.vcenter_username and config.vcenter_password)

    if request.method == 'POST':
        network_name = request.form.get('network_name')
        vm_network = request.form.get('vm_network')
        network_address = request.form.get('network_address')
        subnet_mask = request.form.get('subnet_mask')
        gateway = request.form.get('gateway')
        dns_1 = request.form.get('dns_1')
        dns_2 = request.form.get('dns_2')
        validate_cert = request.form.get('vcenter_validate_certs')
        datacenter = request.form.get('vcenter_datacenter')
        vm_folder = request.form.get('vm_folder')
        disk_datastore = request.form.get('vm_disk_datastore')

        non_domain = NonDomainModel(
            name=network_name,
            vm_network=vm_network,
            network_address=network_address,
            subnet_mask=subnet_mask,
            gateway=gateway,
            dns_1=dns_1,
            dns_2=dns_2,
            validate_cert=validate_cert,
            datacenter=datacenter,
            vm_folder=vm_folder,
            disk_datastore=disk_datastore,
        )

        db.session.add(non_domain)
        db.session.commit()

        log_json('INFO', 'Non-domain network created', network_name=network_name)
        flash(f'Non-Domain Network Created: {network_name}', 'success')

        return redirect('/home')

    return render_template('home/add_network_nondomain.html', vcenter_config=vcenter_config)

@blueprint.route('/add_network_domain', methods=['GET', 'POST'])
@login_required
@admin_required
def add_network_domain():
    log_json('INFO', 'Accessed add network domain route')
    config = ConfigModel.query.get(1)

    vcenter_config = bool(config and config.vcenter_server and config.vcenter_username and config.vcenter_password)

    if request.method == 'POST':
        network_name = request.form.get('network_name')
        vm_network = request.form.get('vm_network')
        network_address = request.form.get('network_address')
        subnet_mask = request.form.get('subnet_mask')
        gateway = request.form.get('gateway')
        dns_1 = request.form.get('dns_1')
        dns_2 = request.form.get('dns_2')
        validate_cert = request.form.get('vcenter_validate_certs')
        datacenter = request.form.get('vcenter_datacenter')
        vm_folder = request.form.get('vm_folder')
        disk_datastore = request.form.get('vm_disk_datastore')
        domain_name = request.form.get('domain_name')
        domain_admin_user = request.form.get('domain_admin_user')
        domain_admin_password = request.form.get('domain_admin_password')

        domain_designation = domain_name.split('.')[0].upper()
        centos_ou_membership = f'OU=Computers,DC={domain_name.replace(".", ",DC=")}'
        ubuntu_ou_membership = f'CN=Computers,DC={domain_name.replace(".", ",DC=")}'

        os.environ[f'{domain_designation}_CENTOS_OU_MEMBERSHIP'] = centos_ou_membership
        os.environ[f'{domain_designation}_UBUNTU_OU_MEMBERSHIP'] = ubuntu_ou_membership

        domain_network = DomainModel(
            name=network_name,
            vm_network=vm_network,
            network_address=network_address,
            subnet_mask=subnet_mask,
            gateway=gateway,
            dns_1=dns_1,
            dns_2=dns_2,
            validate_cert=validate_cert,
            datacenter=datacenter,
            vm_folder=vm_folder,
            disk_datastore=disk_datastore,
            domain_name=domain_name,
            domain_admin_user=domain_admin_user,
            ad_centos_ou_membership=centos_ou_membership,
            ad_ubu_ou_membership=ubuntu_ou_membership
        )
        domain_network.domain_admin_password = domain_admin_password

        db.session.add(domain_network)
        db.session.commit()

        log_json('INFO', 'Domain network created', network_name=network_name)
        flash(f'Domain Network Created: {network_name}', 'success')

        return redirect('/home')

    return render_template('home/add_network_domain.html', vcenter_config=vcenter_config)

@blueprint.route('/view_non_domain_item/<int:item_id>')
@login_required
def view_non_domain_item(item_id):
    log_json('INFO', 'View non-domain item request received', item_id=item_id)
    non_domain_item = NonDomainModel.query.get(item_id)
    if non_domain_item:
        vm_images = VmImageModel.query.filter_by(network_type='non-domain').all()
        return render_template('home/generic/non-domain.html', non_domain_item=non_domain_item, vm_images=vm_images)
    else:
        log_json('ERROR', 'Non-domain item not found', item_id=item_id)
        flash("Item not found", "error")
        return redirect(url_for('home_blueprint.home'))
    
@blueprint.route('/view_non_domain_item_dev/<int:item_id>')
@login_required
def view_non_domain_item_dev(item_id):
    log_json('INFO', 'View non-domain item request received', item_id=item_id)
    non_domain_item = NonDomainModel.query.get(item_id)
    if non_domain_item:
        vm_images = VmImageModel.query.filter_by(network_type='non-domain').all()
        return render_template('home/generic/non-domain-dev.html', non_domain_item=non_domain_item, vm_images=vm_images)
    else:
        log_json('ERROR', 'Non-domain item not found', item_id=item_id)
        flash("Item not found", "error")
        return redirect(url_for('home_blueprint.home'))

@blueprint.route('/view_domain_item/<int:item_id>')
@login_required
def view_domain_item(item_id):
    log_json('INFO', 'View domain item request received', item_id=item_id)
    domain_item = DomainModel.query.get(item_id)
    if domain_item:
        vm_images = VmImageModel.query.filter_by(network_type='domain').all()
        return render_template('home/generic/domain.html', domain_item=domain_item, vm_images=vm_images)
    else:
        log_json('ERROR', 'Domain item not found', item_id=item_id)
        flash("Item not found", "error")
        return redirect(url_for('home_blueprint.home'))


@blueprint.route('/ansible_log/<int:history_id>', methods=['GET'])
@login_required
def get_ansible_log(history_id):
    history = History.query.get_or_404(history_id)
    log_content = ""
    try:
        with open(history.ansible_log_path, 'r') as file:
            log_content = file.read()
    except FileNotFoundError:
        log_content = "Log file not found."
        log_json('ERROR', 'Log file not found', history_id=history_id, path=history.ansible_log_path)

    return jsonify({'log_content': log_content})

@blueprint.route('/log.json')
@login_required
def get_json_logs():
    logs = []
    try:
        with open('logs/app_json.log', 'r') as file:
            for line in reversed(file.readlines()):
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logging.error(f'Error decoding JSON log entry: {e} - Line: {line}')
    except FileNotFoundError:
        logging.error('Log file not found: logs/app_json.log')
        return jsonify({'error': 'Log file not found.'}), 404
    except Exception as e:
        logging.error(f'Unexpected error: {e}')
        return jsonify({'error': 'Unexpected error occurred.'}), 500
    
    return jsonify(logs)

@blueprint.route('/get_settings', methods=['GET'])
def get_settings():
    item_id = request.args.get('item_id')
    domain_item = DomainModel.query.get(item_id)
    default_settings = DefaultVmSettingsModel.query.first()

    if not domain_item or not default_settings:
        return jsonify({'error': 'No settings found'}), 404

    settings = {
        'VM State': default_settings.vm_state,
        'Linux Disk Size': default_settings.linux_disk_size,
        'Windows Disk Size': default_settings.windows_disk_size,
        'VM HW SCSI': default_settings.vm_hw_scsi,
        'VM Type': default_settings.vm_type,
        'Timezone': default_settings.timezone,
        'NTP Servers': default_settings.ntp_servers,
        'AD Upstream DNS1': default_settings.ad_upstream_dns1,
        'AD Upstream DNS2': default_settings.ad_upstream_dns2,
        'Linux Template Username': default_settings.linux_template_username,
        'Windows Template Username': default_settings.windows_template_username,
        'Domain Name': domain_item.domain_name,
        'Domain Admin User': domain_item.domain_admin_user,
        'Network Address': domain_item.network_address,
        'Subnet Mask': domain_item.subnet_mask,
        'Gateway': domain_item.gateway,
        'DNS 1': domain_item.dns_1,
        'DNS 2': domain_item.dns_2,
        'Validate Cert': domain_item.validate_cert,
        'Datacenter': domain_item.datacenter,
        'VM Folder': domain_item.vm_folder,
        'Disk Datastore': domain_item.disk_datastore,
        'AD CentOS OU Membership': domain_item.ad_centos_ou_membership,
        'AD Ubuntu OU Membership': domain_item.ad_ubu_ou_membership,
    }

    return jsonify(settings)

@blueprint.route('/get_settings_non_domain', methods=['GET'])
def get_settings_non_domain():
    item_id = request.args.get('item_id')
    non_domain_item = NonDomainModel.query.get(item_id)
    default_settings = DefaultVmSettingsModel.query.first()

    if not non_domain_item or not default_settings:
        return jsonify({'error': 'No settings found'}), 404

    settings = {
        'VM State': default_settings.vm_state,
        'Linux Disk Size': default_settings.linux_disk_size,
        'Windows Disk Size': default_settings.windows_disk_size,
        'VM HW SCSI': default_settings.vm_hw_scsi,
        'VM Type': default_settings.vm_type,
        'Timezone': default_settings.timezone,
        'NTP Servers': default_settings.ntp_servers,
        'AD Upstream DNS1': default_settings.ad_upstream_dns1,
        'AD Upstream DNS2': default_settings.ad_upstream_dns2,
        'Linux Template Username': default_settings.linux_template_username,
        'Windows Template Username': default_settings.windows_template_username,
        'Network Name': non_domain_item.name,
        'Network Address': non_domain_item.network_address,
        'Subnet Mask': non_domain_item.subnet_mask,
        'Gateway': non_domain_item.gateway,
        'DNS 1': non_domain_item.dns_1,
        'DNS 2': non_domain_item.dns_2,
        'Validate Cert': non_domain_item.validate_cert,
        'Datacenter': non_domain_item.datacenter,
        'VM Folder': non_domain_item.vm_folder,
        'Disk Datastore': non_domain_item.disk_datastore,
    }

    return jsonify(settings)

@blueprint.route('/export_history_csv')
@login_required
def export_history_csv():
    data = History.query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'Start Time', 'End Time', 'Status', 'IP Address', 'Hostname', 'Image Type', 'CPU', 'RAM', 'Environment'])
    
    # Write data
    for row in data:
        writer.writerow([row.id, row.starttime, row.endtime, row.status, row.ipaddress, row.hostname, row.imagetype, row.cpu, row.ram, row.env])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=deployaroo_history_export.csv"}
    )

@blueprint.route('/export_history_pdf')
@login_required
def export_history_pdf():
    data = History.query.all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph("VM Build History", styles['Title']))
    elements.append(Spacer(1, 12))

    # Prepare data for the table
    table_data = [['ID', 'Start Time', 'End Time', 'Status', 'IP Address', 'Hostname', 'Image Type', 'CPU', 'RAM', 'Environment']]
    for row in data:
        table_data.append([str(row.id), row.starttime, row.endtime, row.status, row.ipaddress, row.hostname, row.imagetype, str(row.cpu), str(row.ram), row.env])

    # Create the table
    table = Table(table_data)
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ])
    table.setStyle(style)
    elements.append(table)

    # Build the PDF
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name='deployaroo_history_export.pdf',
        mimetype='application/pdf'
    )

@blueprint.route('/execute_post_build_action/<int:vm_id>/<action>', methods=['POST'])
@login_required
@admin_required
def execute_post_build_action(vm_id, action):
    if action == 'update_os':
        return update_os(vm_id)
    elif action == 'increase_disk':
        return increase_disk_size(vm_id, request.json.get('size'))
    elif action == 'change_password':
        username = request.json.get('username')
        password = request.json.get('password')
        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password are required.'}), 400
        return change_user_password(vm_id, username, password)
    else:
        return jsonify({'success': False, 'message': 'Invalid action.'}), 400

def increase_disk_size(vm_id, new_size):
    def generate():
        try:
            yield "data: Starting disk resize process...\n\n"
            
            vm_record = History.query.get(vm_id)
            if not vm_record:
                yield "data: Error: VM not found in database.\n\n"
                yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
                return

            config = ConfigModel.query.first()
            if not config:
                yield "data: Error: vCenter configuration not found in database.\n\n"
                yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
                return

            yield "data: Connecting to vCenter...\n\n"
            
            # Connect to vCenter
            si = connect.SmartConnect(host=config.vcenter_server,
                                      user=config.vcenter_username,
                                      pwd=config.vcenter_password,
                                      port=443)
            
            content = si.RetrieveContent()
            vm = find_vm_by_name(content, vm_record.hostname)
            
            if not vm:
                yield "data: Error: VM not found in vCenter.\n\n"
                yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
                return

            yield f"data: VM '{vm_record.hostname}' found. Preparing to resize disk...\n\n"

            # Convert new_size to KB
            new_size_kb = int(new_size) * 1024 * 1024

            disk_resized = False
            for device in vm.config.hardware.device:
                if isinstance(device, vim.vm.device.VirtualDisk):
                    current_size_gb = device.capacityInKB / (1024 * 1024)
                    if device.capacityInKB < new_size_kb:
                        yield f"data: Current disk size: {current_size_gb:.2f} GB. Increasing to {new_size} GB...\n\n"
                        
                        spec = vim.vm.ConfigSpec()
                        disk_spec = vim.vm.device.VirtualDeviceSpec()
                        disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
                        disk_spec.device = device
                        disk_spec.device.capacityInKB = new_size_kb
                        spec.deviceChange = [disk_spec]
                        
                        task = vm.Reconfigure(spec)
                        
                        yield "data: Disk resize task initiated. Waiting for completion...\n\n"
                        
                        # Wait for the task to complete
                        while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
                            time.sleep(2)
                            yield "data: Still resizing...\n\n"
                        
                        if task.info.state == vim.TaskInfo.State.success:
                            yield f"data: Disk successfully resized to {new_size} GB.\n\n"
                            disk_resized = True
                        else:
                            yield f"data: Error: Failed to resize disk. {task.info.error.msg}\n\n"
                        
                        break
                    else:
                        yield f"data: Current disk size ({current_size_gb:.2f} GB) is already larger than or equal to requested size ({new_size} GB).\n\n"
                        yield "event: resizeComplete\ndata: Disk resize process completed\n\n"
                        return

            if not disk_resized:
                yield "data: No suitable disk found for resize operation.\n\n"
                yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
                return

            # Update the VM record in the database
            if is_windows_os(vm_record.group):
                vm_record.windows_disk_size = str(new_size)
            else:
                vm_record.linux_disk_size = str(new_size)
            db.session.commit()

            yield "data: VM record updated in database.\n\n"

            # Extend the partition
            if is_windows_os(vm_record.group):
                yield "data: Initiating Windows partition extension...\n\n"
                result = extend_windows_partition(vm_record)
            else:
                yield "data: Initiating Linux partition extension...\n\n"
                result = extend_linux_partition(vm_record)

            if result['success']:
                yield f"data: {result['message']}\n\n"
            else:
                yield f"data: Error: {result['message']}\n\n"

            yield "event: resizeComplete\ndata: Disk resize process finished\n\n"

        except ValueError:
            yield "data: Error: Invalid disk size provided. Please enter a valid number.\n\n"
            yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
        except Exception as e:
            yield f"data: Error: An unexpected error occurred: {str(e)}\n\n"
            yield "event: resizeComplete\ndata: Disk resize process failed\n\n"
        finally:
            if 'si' in locals():
                connect.Disconnect(si)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# def change_user_password(vm_record, username, new_password):
#     # This is a placeholder. You'll need to implement the actual password change logic.
#     # It might involve running a script on the VM or using other methods depending on the OS.
#     # For now, we'll just pretend it worked:
#     return jsonify({'success': True, 'message': f'Password change for user {username} initiated.'})

def find_vm_by_name(content, vm_name):
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    for vm in container.view:
        if vm.name == vm_name:
            return vm
    return None

def determine_os_type(vm):
    logger = logging.getLogger(__name__)
    
    if not isinstance(vm, vim.VirtualMachine):
        logger.error(f"Invalid VM object passed to determine_os_type: {type(vm)}")
        return 'unknown'

    guest_id = vm.config.guestId.lower()
    logger.info(f"Determining OS type for VM: {vm.name}, Guest ID: {guest_id}")

    if 'windows' in guest_id:
        logger.info(f"OS type determined as Windows for VM: {vm.name}")
        return 'windows'
    elif 'centos' in guest_id:
        logger.info(f"OS type determined as CentOS for VM: {vm.name}")
        return 'centos'
    elif 'ubuntu' in guest_id:
        logger.info(f"OS type determined as Ubuntu for VM: {vm.name}")
        return 'ubuntu'
    elif 'rhel' in guest_id or 'red hat' in guest_id:
        logger.info(f"OS type determined as Red Hat for VM: {vm.name}")
        return 'rhel'
    elif 'linux' in guest_id:
        logger.info(f"OS type determined as generic Linux for VM: {vm.name}")
        return 'linux'
    else:
        logger.warning(f"Unknown OS type for VM: {vm.name}, Guest ID: {guest_id}")
        return 'unknown'

def install_pswindowsupdate_module(session, timeout=10):
    def run_installation():
        nonlocal result
        # Set TLS 1.2 (sometimes necessary for older systems)
        session.run_ps("[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12")
        
        # Try to install using Install-Module
        result = session.run_ps("Install-Module -Name PSWindowsUpdate -Force -AllowClobber -Verbose")
        
        if result.status_code != 0:
            # If Install-Module fails, try alternative method
            result = session.run_ps("""
            $url = 'https://www.powershellgallery.com/api/v2/package/PSWindowsUpdate'
            $outputPath = 'C:\\PSWindowsUpdate.zip'
            Invoke-WebRequest -Uri $url -OutFile $outputPath
            Expand-Archive -Path $outputPath -DestinationPath 'C:\\Program Files\\WindowsPowerShell\\Modules\\PSWindowsUpdate' -Force
            Remove-Item $outputPath
            Import-Module PSWindowsUpdate -Force
            """)

    result = None
    thread = threading.Thread(target=run_installation)
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        # Timeout occurred
        thread.join()
        return None, "Timeout occurred while installing PSWindowsUpdate module."
    
    if result.status_code != 0:
        return False, f"Error installing PSWindowsUpdate module: {result.std_err.decode()}"
    
    return True, "PSWindowsUpdate module installed successfully."

def update_windows(vm_record):
    output = []
    try:
        output.append(f"Starting Windows update process for VM {vm_record.hostname}...")
        
        session = winrm.Session(vm_record.ipaddress, auth=(vm_record.windows_template_username, vm_record.windows_template_password), transport='ntlm')
        
        output.append("Checking connection to VM...")
        result = session.run_cmd('ipconfig')
        if result.status_code != 0:
            raise Exception(f"Failed to connect to VM. Error: {result.std_err.decode()}")

        output.append("Connection successful. Proceeding with update check...")

        output.append("Checking for available updates...")
        check_updates_script = """
        $updateSession = New-Object -ComObject Microsoft.Update.Session
        $searcher = $updateSession.CreateUpdateSearcher()
        $searchResult = $searcher.Search("IsInstalled=0")
        $updates = $searchResult.Updates | Select-Object Title, Description, IsDownloaded, IsMandatory
        ConvertTo-Json -InputObject @($updates)
        """
        result = session.run_ps(check_updates_script)
        
        if result.status_code != 0:
            raise Exception(f"Error checking for updates: {result.std_err.decode()}")

        updates = json.loads(result.std_out.decode())
        output.append(f"Found {len(updates)} updates available.")

        if len(updates) == 0:
            output.append("No updates available. Windows is up to date.")
            return output

        output.append("Installing updates...")
        install_updates_script = """
        $updateSession = New-Object -ComObject Microsoft.Update.Session
        $searcher = $updateSession.CreateUpdateSearcher()
        $searchResult = $searcher.Search("IsInstalled=0")
        $updates = $searchResult.Updates
        $downloader = $updateSession.CreateUpdateDownloader()
        $downloader.Updates = $updates
        $downloadResult = $downloader.Download()
        $installer = $updateSession.CreateUpdateInstaller()
        $installer.Updates = $updates
        $installationResult = $installer.Install()
        ConvertTo-Json -InputObject @{
            'ResultCode' = $installationResult.ResultCode
            'RebootRequired' = $installationResult.RebootRequired
            'HResult' = $installationResult.HResult
        }
        """
        result = session.run_ps(install_updates_script)
        
        if result.status_code != 0:
            raise Exception(f"Error installing updates: {result.std_err.decode()}")

        installation_result = json.loads(result.std_out.decode())
        output.append(f"Update installation result: {json.dumps(installation_result, indent=2)}")

        if installation_result['RebootRequired']:
            output.append("Reboot required. Initiating reboot...")
            session.run_cmd('shutdown', ['/r', '/t', '0'])
        else:
            output.append("Updates installed successfully. No reboot required.")

        output.append(f"Windows update process completed for VM {vm_record.hostname}.")

    except Exception as e:
        output.append(f"Error updating Windows VM {vm_record.hostname}: {str(e)}")

    return output

def update_linux(vm_record, os_type):
    output = []
    ssh = None
    try:
        output.append(f"Starting Linux update process for VM {vm_record.hostname}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(vm_record.ipaddress, 
                    username=vm_record.linux_template_username, 
                    password=vm_record.linux_template_password)

        output.append("Connected to VM. Starting update process...")

        if os_type in ['ubuntu', 'debian']:
            output.append("Updating package lists...")
            stdin, stdout, stderr = ssh.exec_command('sudo apt update')
            output.extend(stdout.readlines())
            
            output.append("Upgrading packages...")
            stdin, stdout, stderr = ssh.exec_command('sudo apt upgrade -y')
            output.extend(stdout.readlines())

        elif os_type in ['centos', 'rhel']:
            output.append("Updating packages...")
            stdin, stdout, stderr = ssh.exec_command('sudo yum update -y')
            output.extend(stdout.readlines())

        else:  # generic Linux
            output.append("Detecting package manager and updating...")
            stdin, stdout, stderr = ssh.exec_command(
                'if command -v apt-get &> /dev/null; then '
                'sudo apt update && sudo apt upgrade -y; '
                'elif command -v yum &> /dev/null; then '
                'sudo yum update -y; '
                'else echo "Unsupported package manager"; exit 1; fi'
            )
            output.extend(stdout.readlines())

        output.append(f"Update process completed for VM {vm_record.hostname}.")

    except Exception as e:
        output.append(f"Error updating Linux VM {vm_record.hostname}: {str(e)}")
    finally:
        if ssh:
            ssh.close()

    return output

def is_debian_based(ssh):
    stdin, stdout, stderr = ssh.exec_command('cat /etc/os-release')
    os_release = stdout.read().decode('utf-8').lower()
    return 'debian' in os_release or 'ubuntu' in os_release

def is_rhel_based(ssh):
    stdin, stdout, stderr = ssh.exec_command('cat /etc/os-release')
    os_release = stdout.read().decode('utf-8').lower()
    return 'rhel' in os_release or 'centos' in os_release or 'fedora' in os_release

def update_os(vm_id):
    def generate():
        vm_record = History.query.get(vm_id)
        if not vm_record:
            yield f"data: VM record not found in database for ID: {vm_id}\n\n"
            return

        # Log start of update process
        log_json('INFO', f"OS Update Started: {vm_record.hostname}", vm_id=vm_id, hostname=vm_record.hostname)
        yield f"data: Starting update process for VM {vm_record.hostname}...\n\n"

        update_output = []
        status = 'Running'
        start_time = datetime.now()

        try:
            config = ConfigModel.query.first()
            if not config:
                raise ValueError("vCenter configuration not found in database.")

            update_output.append("Connecting to vCenter...")
            yield "data: Connecting to vCenter...\n\n"

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            si = connect.SmartConnect(host=config.vcenter_server,
                                      user=config.vcenter_username,
                                      pwd=config.vcenter_password,
                                      port=443,
                                      sslContext=ssl_context)
            
            content = si.RetrieveContent()

            update_output.append("Connected to vCenter. Locating VM...")
            yield "data: Connected to vCenter. Locating VM...\n\n"

            vm = find_vm_by_name(content, vm_record.hostname)
            if not vm:
                raise ValueError(f"VM {vm_record.hostname} not found in vSphere.")

            update_output.append("VM found. Determining OS type...")
            yield "data: VM found. Determining OS type...\n\n"

            os_type = determine_os_type(vm)
            update_output.append(f"OS type determined: {os_type}")
            yield f"data: OS type determined: {os_type}\n\n"

            if os_type == 'windows':
                windows_output = update_windows(vm_record)
                update_output.extend(windows_output)
                for line in windows_output:
                    yield f"data: {line}\n\n"
            elif os_type in ['centos', 'rhel', 'ubuntu', 'linux']:
                linux_output = update_linux(vm_record, os_type)
                update_output.extend(linux_output)
                for line in linux_output:
                    yield f"data: {line}\n\n"
            else:
                raise ValueError(f"Unsupported OS type for VM {vm_record.hostname}.")

            status = 'Completed'
            update_output.append(f"Update process completed for VM {vm_record.hostname}.")
            yield f"data: Update process completed for VM {vm_record.hostname}.\n\n"

        except Exception as e:
            error_message = f"Error during update process: {str(e)}"
            update_output.append(error_message)
            yield f"data: {error_message}\n\n"
            status = 'Failed'

        finally:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Log the complete output
            log_json('INFO', f"OS Update Output {vm_record.hostname}", vm_id=vm_id, hostname=vm_record.hostname, output=update_output)
            
            # Log completion of update process
            log_json('INFO', f"OS Update Finished: {vm_record.hostname}", 
                     vm_id=vm_id, 
                     hostname=vm_record.hostname,
                     duration=f"{duration:.2f} seconds",
                     )

            if 'si' in locals():
                connect.Disconnect(si)

        yield f"data: {json.dumps({'status': status, 'message': 'Update process finished'})}\n\n"
        yield "event: updateComplete\ndata: Update process finished\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

def change_user_password(vm_id, username, new_password):
    def generate():
        si = None
        try:
            yield "data: Initiating password change process...\n\n"
            vm_record = History.query.get(vm_id)
            if not vm_record:
                yield "data: Error: VM not found in database.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Retrieving vCenter configuration...\n\n"
            config = ConfigModel.query.first()
            if not config:
                yield "data: Error: vCenter configuration not found in database.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Connecting to vCenter...\n\n"
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            si = connect.SmartConnect(host=config.vcenter_server,
                                      user=config.vcenter_username,
                                      pwd=config.vcenter_password,
                                      port=443,
                                      sslContext=ssl_context)

            yield "data: Retrieving VM information...\n\n"
            content = si.RetrieveContent()
            vm = get_vm_by_name(content, vm_record.hostname)

            if not vm:
                yield "data: Error: VM not found in VMware.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Determining OS type...\n\n"
            os_type = determine_os_type(vm)

            if os_type == 'windows':
                yield "data: Detected Windows OS. Initiating Windows password change...\n\n"
                result = change_windows_password(vm_record, username, new_password)
                if result['success']:
                    vm_record.windows_template_password = new_password
            elif os_type in ['centos', 'rhel', 'ubuntu', 'linux']:
                yield "data: Detected Linux OS. Initiating Linux password change...\n\n"
                result = change_linux_password(vm_record, username, new_password)
                if result['success']:
                    vm_record.linux_template_password = new_password
            else:
                yield f"data: Error: Unsupported OS type for VM {vm_record.hostname}.\n\n"
                yield "event: updateComplete\n\n"
                return

            if result['success']:
                yield "data: Password changed successfully. Updating Deployaroo database...\n\n"
                db.session.commit()
                log_json('INFO', f"Password changed successfully for user {username} on VM {vm_record.hostname}", vm_id=vm_id)
                yield "data: Process completed successfully.\n\n"
                yield "event: updateComplete\n\n"
            else:
                yield f"data: Error: {result['message']}\n\n"
                yield "event: updateComplete\n\n"
                log_json('ERROR', f"Failed to change password for user {username} on VM {vm_record.hostname}", vm_id=vm_id, error=result['message'])

        except Exception as e:
            log_json('ERROR', f"Error changing password for VM {vm_id}", error=str(e))
            yield f"data: An error occurred: {str(e)}\n\n"
            yield "event: updateComplete\n\n"
        finally:
            if si:
                connect.Disconnect(si)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

def change_windows_password(vm_record, username, new_password):
    try:
        session = winrm.Session(vm_record.ipaddress, auth=(vm_record.windows_template_username, vm_record.windows_template_password), transport='ntlm')
        
        # Escape special characters in the password
        escaped_password = new_password.replace('"', '`"').replace('$', '`$')
        
        # PowerShell command to change the password
        command = f'$SecPassword = ConvertTo-SecureString "{escaped_password}" -AsPlainText -Force; Set-LocalUser -Name "{username}" -Password $SecPassword'
        
        result = session.run_ps(command)
        
        if result.status_code == 0:
            return {'success': True, 'message': f'Password changed successfully for user {username}.'}
        else:
            return {'success': False, 'message': f'Failed to change password: {result.std_err.decode()}'}
    
    except Exception as e:
        return {'success': False, 'message': f'Error changing Windows password: {str(e)}'}

def change_linux_password(vm_record, username, new_password):
    ssh = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(vm_record.ipaddress, 
                    username=vm_record.linux_template_username, 
                    password=vm_record.linux_template_password)

        # Escape special characters in the password
        escaped_password = new_password.replace("'", "'\"'\"'")
        
        # Command to change the password
        command = f"echo '{username}:{escaped_password}' | sudo chpasswd"
        
        stdin, stdout, stderr = ssh.exec_command(command)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status == 0:
            return {'success': True, 'message': f'Password changed successfully for user {username}.'}
        else:
            error = stderr.read().decode('utf-8')
            return {'success': False, 'message': f'Failed to change password: {error}'}

    except Exception as e:
        return {'success': False, 'message': f'Error changing Linux password: {str(e)}'}
    
    finally:
        if ssh:
            ssh.close()

def increase_disk_size(vm_id, new_size):
    def generate():
        try:
            yield "data: Initiating disk size increase process...\n\n"
            
            vm_record = History.query.get(vm_id)
            if not vm_record:
                yield "data: Error: VM not found in database.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Retrieving vCenter configuration...\n\n"
            config = ConfigModel.query.first()
            if not config:
                yield "data: Error: vCenter configuration not found in database.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Determining current disk size...\n\n"
            current_size = int(vm_record.windows_disk_size if is_windows_os(vm_record.group) else vm_record.linux_disk_size)
            new_size_kb = int(new_size) * 1024 * 1024

            if int(new_size) <= current_size:
                yield f"data: Error: New size must be larger than current size ({current_size} GB).\n\n"
                yield "event: updateComplete\n\n"
                return

            yield "data: Connecting to vCenter...\n\n"
            ssl_context = create_unverified_ssl_context()
            si = connect.SmartConnect(host=config.vcenter_server,
                                      user=config.vcenter_username,
                                      pwd=config.vcenter_password,
                                      port=443,
                                      sslContext=ssl_context)
            content = si.RetrieveContent()

            yield f"data: Locating VM {vm_record.hostname} in vCenter...\n\n"
            vm = find_vm_by_name(content, vm_record.hostname)
            if not vm:
                yield "data: Error: VM not found in vCenter.\n\n"
                yield "event: updateComplete\n\n"
                return

            yield f"data: Increasing disk size to {new_size} GB in vSphere...\n\n"
            task = increase_disk_size_vsphere(vm, new_size_kb)
            wait_for_tasks(si, [task])

            os_type = 'windows' if is_windows_os(vm_record.group) else 'linux'
            yield f"data: Detected {os_type.capitalize()} OS. Extending partition...\n\n"

            if os_type == 'windows':
                result = extend_windows_partition(vm_record)
            else:
                result = extend_linux_partition(vm_record)

            if result['success']:
                yield "data: Partition extended successfully. Updating database...\n\n"
                if os_type == 'windows':
                    vm_record.windows_disk_size = str(new_size)
                else:
                    vm_record.linux_disk_size = str(new_size)
                db.session.commit()
                log_json('INFO', f"Disk size increased and partition extended for VM {vm_record.hostname}", vm_id=vm_id, new_size=new_size)
                yield f"data: Disk size increased to {new_size} GB and partition extended successfully.\n\n"
            else:
                yield f"data: Error: Disk size increased but failed to extend partition: {result['message']}\n\n"
                log_json('ERROR', f"Failed to extend partition for VM {vm_record.hostname}", vm_id=vm_id, error=result['message'])

            yield "event: updateComplete\n\n"

        except Exception as e:
            error_message = str(e)
            log_json('ERROR', f"Error increasing disk size for VM {vm_id}", error=error_message)
            yield f"data: An error occurred: {error_message}\n\n"
            yield "event: updateComplete\n\n"
        finally:
            if 'si' in locals():
                connect.Disconnect(si)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

def increase_disk_size_vsphere(vm, new_size_kb):
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualDisk):
            dev_changes = []
            disk_spec = vim.vm.device.VirtualDeviceSpec()
            disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
            disk_spec.device = dev
            disk_spec.device.capacityInKB = new_size_kb
            dev_changes.append(disk_spec)
            spec = vim.vm.ConfigSpec()
            spec.deviceChange = dev_changes
            return vm.ReconfigVM_Task(spec=spec)

def wait_for_tasks(si, tasks):
    property_collector = si.content.propertyCollector
    task_list = [str(task) for task in tasks]
    obj_specs = [vim.PropertyCollector.ObjectSpec(obj=task) for task in tasks]
    property_spec = vim.PropertyCollector.PropertySpec(type=vim.Task, pathSet=[], all=True)
    filter_spec = vim.PropertyCollector.FilterSpec()
    filter_spec.objectSet = obj_specs
    filter_spec.propSet = [property_spec]
    pcfilter = property_collector.CreateFilter(filter_spec, True)
    try:
        version, state = None, None
        while len(task_list):
            update = property_collector.WaitForUpdates(version)
            for filter_set in update.filterSet:
                for obj_set in filter_set.objectSet:
                    task = obj_set.obj
                    for change in obj_set.changeSet:
                        if change.name == 'info':
                            state = change.val.state
                        elif change.name == 'info.state':
                            state = change.val
                        else:
                            continue
                        if state == vim.TaskInfo.State.success:
                            task_list.remove(str(task))
                        elif state == vim.TaskInfo.State.error:
                            raise task.info.error
            version = update.version
    finally:
        if pcfilter:
            pcfilter.Destroy()

def extend_windows_partition(vm_record):
    try:
        session = winrm.Session(vm_record.ipaddress, auth=(vm_record.windows_template_username, vm_record.windows_template_password), transport='ntlm')
        
        # PowerShell script to extend the partition
        script = """
        $maxSize = (Get-PartitionSupportedSize -DriveLetter C).SizeMax
        Resize-Partition -DriveLetter C -Size $maxSize
        """
        
        result = session.run_ps(script)
        
        if result.status_code == 0:
            return {'success': True, 'message': 'Windows partition extended successfully.'}
        else:
            return {'success': False, 'message': f'Failed to extend Windows partition: {result.std_err.decode()}'}
    
    except Exception as e:
        return {'success': False, 'message': f'Error extending Windows partition: {str(e)}'}

def extend_linux_partition(vm_record, restart_after_resize=True):
    ssh = None
    command_outputs = []
    try:
        # Log the start of the disk expansion
        log_json('INFO', f"Started expand disk on {vm_record.hostname}", vm_id=vm_record.id)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(vm_record.ipaddress, 
                    username=vm_record.linux_template_username, 
                    password=vm_record.linux_template_password)

        def run_command(cmd):
            stdin, stdout, stderr = ssh.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()
            command_outputs.append({
                'command': cmd,
                'output': output,
                'error': error,
                'exit_status': exit_status
            })
            return output, error, exit_status

        # Determine OS version
        os_version, _, _ = run_command("cat /etc/os-release | grep VERSION_ID | cut -d'=' -f2 | tr -d '\"'")
        os_version = os_version.strip()

        # Check current setup
        run_command("lsblk")
        run_command("df -h")

        if restart_after_resize:
            # Restart the VM
            run_command("sudo reboot")
            # Wait for the VM to restart (adjust the sleep time as needed)
            time.sleep(60)
            
            # Reconnect to the VM
            ssh.connect(vm_record.ipaddress, 
                        username=vm_record.linux_template_username, 
                        password=vm_record.linux_template_password)

        if os_version == '22.04':
            # Ubuntu 22.04 specific steps
            run_command("sudo growpart /dev/sda 3")
            run_command("sudo lvextend -l +100%FREE /dev/mapper/sysvg-root")
            run_command("sudo xfs_growfs /dev/mapper/sysvg-root")
        elif os_version == '20.04':
            # Ubuntu 18.04 and 20.04 specific steps
            run_command("sudo apt-get update && sudo apt-get install -y cloud-guest-utils")
            run_command("sudo growpart /dev/sda 3")
            run_command("sudo pvresize /dev/sda3")
            run_command("sudo lvextend -l +100%FREE /dev/sysvg/root")
            
            # Check filesystem type
            fs_type, _, _ = run_command("df -T / | tail -n 1 | awk '{print $2}'")
            fs_type = fs_type.strip()
            
            if fs_type == 'xfs':
                run_command("sudo xfs_growfs /dev/mapper/sysvg-root")
            else:
                run_command("sudo resize2fs /dev/mapper/sysvg-root")
        elif os_version == '18.04':
            # Ubuntu 18.04 specific steps
            run_command("sudo apt-get update && sudo apt-get install -y cloud-guest-utils")
            run_command("sudo growpart /dev/sda 3")
            run_command("sudo pvresize /dev/sda3")
            
            # Get VG name
            vg_name, _, _ = run_command("sudo vgs --noheadings -o vg_name")
            vg_name = vg_name.strip()
            
            # Get LV name for root
            lv_name, _, _ = run_command(f"sudo lvs {vg_name} --noheadings -o lv_name | grep root")
            lv_name = lv_name.strip()
            
            run_command(f"sudo lvextend -l +100%FREE /dev/{vg_name}/{lv_name}")
            
            # Check filesystem type
            fs_type, _, _ = run_command("df -T / | tail -n 1 | awk '{print $2}'")
            fs_type = fs_type.strip()
            
            if fs_type == 'xfs':
                run_command(f"sudo xfs_growfs /dev/{vg_name}/{lv_name}")
            else:
                run_command(f"sudo resize2fs /dev/{vg_name}/{lv_name}")
        elif os_version.startswith('7'):  # CentOS 7
            run_command("sudo yum install -y cloud-utils-growpart gdisk")
            run_command("sudo growpart /dev/sda 3")
            run_command("sudo pvresize /dev/sda3")
            run_command("sudo lvextend -l +100%FREE /dev/sysvg/lv_root")
            fs_type, _, _ = run_command("df -T / | tail -n 1 | awk '{print $2}'")
            fs_type = fs_type.strip()
            if fs_type == 'xfs':
                run_command("sudo xfs_growfs /dev/sysvg/lv_root")
            else:
                run_command("sudo resize2fs /dev/sysvg/lv_root")

        # Final check
        run_command("lsblk")
        run_command("df -h")

        # Log all command outputs
        log_json('INFO', f"Command outputs for {vm_record.hostname}", vm_id=vm_record.id, command_outputs=command_outputs)

        # Log the completion of the disk expansion
        log_json('INFO', f"Finished expand disk on {vm_record.hostname}", vm_id=vm_record.id)

        return {'success': True, 'message': f'Linux partition extension completed for OS version {os_version}. Please check logs for details.'}

    except Exception as e:
        log_json('ERROR', f"Error extending Linux partition for VM {vm_record.hostname}", error=str(e), vm_id=vm_record.id)
        return {'success': False, 'message': f'Error extending Linux partition: {str(e)}'}
    
    finally:
        if ssh:
            ssh.close()

def is_windows_os(group):
    windows_groups = [
        'win31Guest', 'win95Guest', 'win98Guest', 'winntGuest', 'win2000ProGuest',
        'win2000ServGuest', 'win2000AdvServGuest', 'winXPProGuest', 'winXPPro64Guest',
        'winNetEnterpriseGuest', 'winNetDatacenterGuest', 'winNetStandardGuest',
        'winNetWebGuest', 'winNetBusinessGuest', 'winNetEnterprise64Guest',
        'winNetDatacenter64Guest', 'winNetStandard64Guest', 'winVistaGuest',
        'winVista64Guest', 'winLonghornGuest', 'winLonghorn64Guest', 'windows7Guest',
        'windows7_64Guest', 'windows7Server64Guest', 'windows8Guest', 'windows8_64Guest',
        'windows8Server64Guest', 'windows9Guest', 'windows9_64Guest',
        'windows9Server64Guest', 'windows2019srv_64Guest'
    ]
    return group in windows_groups

def create_unverified_ssl_context():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context