from io import BytesIO, StringIO
from flask import make_response
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
from datetime import datetime
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
            History.env.ilike(f'%{search_query}%')
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
        # Fetch the VM details from your database
        vm = History.query.get(vm_id)
        if vm:
            details = {
                'hostname': vm.hostname,
                'ipaddress': vm.ipaddress,
                'imagetype': vm.imagetype,
                'env': vm.env,
                'cpu': vm.cpu,
                'ram': vm.ram,
                'status': vm.status,
                'starttime': vm.starttime,
                'endtime': vm.endtime,
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
    item_environment_name, item_playbook_location = handle_item_id(environment, item_id)
    
    environment_name = item_environment_name or environment_name
    playbook_location = item_playbook_location or playbook_location

    domain_item = DomainModel.query.get(item_id)
    non_domain_item = NonDomainModel.query.get(item_id)
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
            'cpu': request.form.get('cpu'),
            'ram': request.form.get('ram'),
        }]

    for client_machine in client_machines:
        ipaddress = client_machine['ipaddress']
        hostname = client_machine['hostname']
        imagetype = client_machine['imagetype']
        machinetype = client_machine['machinetype']
        group = client_machine['group']
        cpu = client_machine['cpu']
        ram = client_machine['ram']

        timestamp = time.strftime('%Y%m%d%H%M%S')
        log_file_name = f"{timestamp}_{hostname}.log"
        pwd = os.getcwd()
        ansible_log_path = os.path.join(f'{pwd}/logs/build_logs', log_file_name)

        new_history = History(
            starttime=time.strftime('%A %B, %d %Y %H:%M:%S'),
            endtime="In Progress",
            status="Running",
            ipaddress=ipaddress,
            hostname=hostname,
            imagetype=imagetype,
            cpu=cpu,
            ram=ram,
            env=environment_name,
            ansible_log_path=ansible_log_path
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