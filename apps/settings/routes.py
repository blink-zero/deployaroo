from datetime import datetime
from functools import wraps
import logging
import os
import json
import shutil
from werkzeug.security import generate_password_hash
import yaml
from apps.config import Config
from apps.home.util import generate_random_password
from apps.models.vm_image_model import VmImageModel
from apps.settings import blueprint
from apps.models import User, Group, PluginModel, DefaultVmSettingsModel, ConfigModel, History, NonDomainModel, DomainModel
from apps.settings.util import model_to_dict
from apps import db
from flask_login import login_required, current_user
from flask import current_app, Response, send_file, abort
from flask import jsonify, render_template, redirect, request, session, url_for
from flask import flash, send_from_directory
from werkzeug.utils import secure_filename
import zipfile
from apps.utils.logging import log_json

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'zip'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return super().default(obj)

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or 1 not in [group.id for group in current_user.groups]:
            return render_template('error/403.html'), 403
        return func(*args, **kwargs)
    return decorated_view

@blueprint.route('/settings')
@login_required
@admin_required
def settings():
    return redirect(url_for('settings_blueprint.settings_general'))

@blueprint.route('/settings/general')
@login_required
@admin_required
def settings_general():
    log_json('INFO', 'Accessed general settings page')
    return render_template('home/settings.html', active_tab='general')

@blueprint.route('/settings/vmware')
@login_required
@admin_required
def settings_vmware():
    log_json('INFO', 'Accessed VMware settings page')
    config = ConfigModel.query.first()
    return render_template('home/settings.html', active_tab='vmware', config=config)

@blueprint.route('/settings/default_vm')
@login_required
@admin_required
def settings_default_vm():
    log_json('INFO', 'Accessed default VM settings page')
    defaultvmsettings = DefaultVmSettingsModel.query.first()
    return render_template('home/settings.html', active_tab='default_vm', defaultvmsettings=defaultvmsettings)

@blueprint.route('/settings/users')
@login_required
@admin_required
def settings_users():
    log_json('INFO', 'Accessed users settings page')
    users = User.query.all()
    groups = Group.query.all()
    return render_template('home/settings.html', active_tab='users', users=users, groups=groups)

@blueprint.route('/settings/backup')
@login_required
@admin_required
def settings_backup():
    log_json('INFO', 'Accessed backup settings page')
    backup_folder = os.path.abspath(os.path.join(current_app.root_path, 'backups'))
    backup_history = []

    try:
        for filename in os.listdir(backup_folder):
            backup_history.append(filename)
        log_json('INFO', 'Backup history retrieved')
    except FileNotFoundError:
        log_json('ERROR', 'Backup folder not found')
        pass

    return render_template('home/settings.html', active_tab='backup', backup_history=backup_history)

@blueprint.route('/settings/vm_images')
@login_required
@admin_required
def settings_vm_images():
    vm_images = VmImageModel.query.all()
    domain_count = sum(1 for image in vm_images if image.network_type == 'domain')
    non_domain_count = sum(1 for image in vm_images if image.network_type != 'domain')
    linux_count = sum(1 for image in vm_images if 'linux' in image.image_type.lower())
    windows_count = sum(1 for image in vm_images if 'windows' in image.image_type.lower())
    
    log_json('INFO', 'Accessed VM images settings page')
    return render_template('home/settings.html', active_tab='vm_images', vm_images=vm_images, domain_count=domain_count, non_domain_count=non_domain_count, linux_count=linux_count, windows_count=windows_count)


@blueprint.route('/settings/scan_images', methods=['POST'])
@login_required
@admin_required
def scan_images():
    pwd = os.getcwd()
    image_paths = {
        f'{pwd}/apps/plugins/ansible-deploy-vm/tasks': 'non-domain',
        f'{pwd}/apps/plugins/ansible-deploy-vm-domain/tasks': 'domain'
    }

    try:
        valid_images = set()

        for images_path, network_type in image_paths.items():
            for folder_name in os.listdir(images_path):
                folder_path = os.path.join(images_path, folder_name)

                if os.path.isdir(folder_path):
                    settings_file = os.path.join(folder_path, 'settings.json')
                    if not os.path.isfile(settings_file):
                        continue

                    with open(settings_file, 'r') as file:
                        config = json.load(file)

                    image_template_name = config.get('image_template_name')
                    image_human_name = config.get('image_human_name', folder_name.replace('_', ' ').title())
                    image_folder_name = folder_name
                    image_type = config.get('image_type', 'default')
                    ansible_match_name = config.get('ansible_match_name', folder_name)
                    vmware_os_type = config.get('vmware_os_type', 'linux')
                    image_icon_name = config.get('image_icon_name', 'icon.png')

                    valid_images.add(image_folder_name)

                    existing_image = VmImageModel.query.filter_by(image_folder_name=image_folder_name).first()
                    if existing_image:
                        existing_image.image_template_name = image_template_name
                        existing_image.image_human_name = image_human_name
                        existing_image.image_type = image_type
                        existing_image.ansible_match_name = ansible_match_name
                        existing_image.vmware_os_type = vmware_os_type
                        existing_image.image_icon_name = image_icon_name
                        existing_image.network_type = network_type
                    else:
                        vm_image = VmImageModel(
                            image_template_name=image_template_name,
                            image_human_name=image_human_name,
                            image_folder_name=image_folder_name,
                            image_type=image_type,
                            ansible_match_name=ansible_match_name,
                            vmware_os_type=vmware_os_type,
                            image_icon_name=image_icon_name,
                            network_type=network_type
                        )

                        db.session.add(vm_image)

        VmImageModel.query.filter(~VmImageModel.image_folder_name.in_(valid_images)).delete(synchronize_session=False)

        db.session.commit()
        log_json('INFO', 'Database has been populated with VM images from folders.')
        return jsonify({'success': True, 'message': 'Images scanned and database populated successfully.'})
    except Exception as e:
        db.session.rollback()
        log_json('ERROR', 'Failed to scan images', error=str(e))
        return jsonify({'success': False, 'message': str(e)})

@blueprint.route('/settings/upload_zip', methods=['POST'])
@login_required
@admin_required
def upload_zip():
    if 'zipfile' not in request.files:
        return jsonify(success=False, message="No file uploaded")
    
    zipfile_obj = request.files['zipfile']
    if zipfile_obj.filename == '' or not allowed_file(zipfile_obj.filename):
        return jsonify(success=False, message="Invalid file")
    
    pwd = os.getcwd()
    upload_folder = os.path.join(pwd, 'apps', 'plugins', 'uploads')
    
    if 'zipfile' not in request.files:
        return jsonify(success=False, message="No file uploaded")
    
    zipfile_obj = request.files['zipfile']
    if zipfile_obj.filename == '':
        return jsonify(success=False, message="No selected file")
    
    filename = secure_filename(zipfile_obj.filename)
    
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    zip_path = os.path.join(upload_folder, filename)
    zipfile_obj.save(zip_path)

    try:
        extracted_folder = os.path.join(upload_folder, os.path.splitext(filename)[0])
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extracted_folder)

        extracted_files = []
        for root, dirs, files in os.walk(extracted_folder):
            for file in files:
                extracted_files.append(os.path.join(root, file))
        current_app.logger.info(f"Extracted files: {extracted_files}")

        settings_path = None
        for root, dirs, files in os.walk(extracted_folder):
            if 'settings.json' in files:
                settings_path = os.path.join(root, 'settings.json')
                break
        
        if not settings_path:
            return jsonify(success=False, message="settings.json not found in the extracted files")

        with open(settings_path) as f:
            settings = json.load(f)

        network_type = settings.get('network_type')
        ansible_match_name = settings.get('ansible_match_name')
        if not network_type:
            return jsonify(success=False, message="network_type not specified in settings.json")
        if not ansible_match_name:
            return jsonify(success=False, message="ansible_match_name not specified in settings.json")

        existing_image = VmImageModel.query.filter_by(ansible_match_name=ansible_match_name).first()
        if existing_image:
            return jsonify(success=False, message=f"Image with ansible_match_name '{ansible_match_name}' already exists")

        target_folder = os.path.join(pwd, 'apps', 'plugins', network_type, 'tasks')
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)

        extracted_base_folder = os.path.basename(extracted_folder)
        if os.path.exists(os.path.join(target_folder, extracted_base_folder)):
            return jsonify(success=False, message="Duplicate folder name detected. File not uploaded.")

        for item in os.listdir(extracted_folder):
            item_path = os.path.join(extracted_folder, item)
            shutil.move(item_path, target_folder)

        yaml_file = 'other_domain.yml' if network_type == 'ansible-deploy-vm-domain' else 'other.yml'
        human_name = settings.get('image_human_name')
        yaml_path = os.path.join(pwd, 'apps', 'plugins', network_type, yaml_file)
        new_task = {
            'name': f"Build {human_name} Virtual Machine",
            'hosts': ansible_match_name,
            'become': False,
            'gather_facts': False,
            'collections': ['community.vmware'],
            'pre_tasks': [{'include_vars': 'vars/other.yml'}],
            'tasks': [{'import_tasks': f'tasks/{extracted_base_folder}/main.yml'}],
            'serial': 1
        }
        
        with open(yaml_path, 'r') as file:
            data = yaml.safe_load(file)
        data.append(new_task)
        
        with open(yaml_path, 'w') as file:
            yaml.dump(data, file, default_flow_style=False, sort_keys=False)
        
        if not scan_images():
            return jsonify(success=False, message="An error occurred while scanning images")

        return jsonify(success=True, message="File uploaded, processed, and images scanned successfully")

    except zipfile.BadZipFile:
        return jsonify(success=False, message="Invalid zip file")
    except Exception as e:
        current_app.logger.error(f"Error processing zip file: {str(e)}")
        return jsonify(success=False, message="An error occurred while processing the zip file")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(extracted_folder):
            shutil.rmtree(extracted_folder)

@blueprint.route('/settings/delete_image/<int:image_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_image(image_id):
    image = VmImageModel.query.get(image_id)
    if not image:
        current_app.logger.error(f"Image with ID {image_id} not found.")
        return jsonify(success=False, message="Image not found")

    pwd = os.getcwd()
    if image.network_type == 'domain':
        base_folder = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm-domain', 'tasks')
    else:
        base_folder = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm', 'tasks')

    folder_path = os.path.join(base_folder, image.image_folder_name)
    marked_for_delete_base = os.path.join(base_folder, '..', 'marked_for_delete')
    marked_for_delete_path = os.path.join(marked_for_delete_base, image.image_folder_name)

    try:
        db.session.delete(image)
        db.session.commit()
        current_app.logger.info(f"Image with ID {image_id} deleted from database.")

        if not os.path.exists(marked_for_delete_base):
            os.makedirs(marked_for_delete_base)

        if os.path.exists(marked_for_delete_base):
            for filename in os.listdir(marked_for_delete_base):
                file_path = os.path.join(marked_for_delete_base, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    current_app.logger.error(f"Failed to delete {file_path}. Reason: {e}")

        if os.path.exists(folder_path):
            shutil.move(folder_path, marked_for_delete_path)
            current_app.logger.info(f"Folder {folder_path} moved to {marked_for_delete_path}.")
        else:
            current_app.logger.warning(f"Folder {folder_path} does not exist.")

        yaml_file = 'other_domain.yml' if image.network_type == 'domain' else 'other.yml'
        if image.network_type == 'domain':
            yaml_path = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm-domain', yaml_file)
        else:
            yaml_path = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm', yaml_file)

        with open(yaml_path, 'r') as file:
            data = yaml.safe_load(file)

        new_data = []
        for task in data:
            if not (isinstance(task, dict) and 'tasks' in task and any(
                    f"tasks/{image.image_folder_name}/main.yml" in t.get('import_tasks', '')
                    for t in task['tasks']
            )):
                new_data.append(task)

        with open(yaml_path, 'w') as file:
            yaml.dump(new_data, file, default_flow_style=False, sort_keys=False)

        return jsonify(success=True, message="Image and associated folder marked for deletion successfully")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting image with ID {image_id}: {str(e)}")
        return jsonify(success=False, message="Error deleting image")


@blueprint.route('/settings/modify_image/<int:image_id>', methods=['POST'])
@login_required
@admin_required
def modify_image(image_id):
    image = VmImageModel.query.get(image_id)
    if not image:
        current_app.logger.error(f"Image with ID {image_id} not found.")
        return jsonify(success=False, message="Image not found")

    data = request.get_json()
    new_image_human_name = data.get('image_human_name', image.image_human_name)
    new_image_template_name = data.get('image_template_name', image.image_template_name)

    current_app.logger.info(f"Received new values for image ID {image_id}:")
    current_app.logger.info(f"New image_human_name: {new_image_human_name}")
    current_app.logger.info(f"New image_template_name: {new_image_template_name}")

    pwd = os.getcwd()
    if image.network_type == 'domain':
        base_folder = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm-domain', 'tasks')
    else:
        base_folder = os.path.join(pwd, 'apps', 'plugins', 'ansible-deploy-vm', 'tasks')

    folder_path = os.path.join(base_folder, image.image_folder_name)
    settings_path = os.path.join(folder_path, 'settings.json')

    try:
        current_app.logger.info(f"Targeting settings.json at path: {settings_path}")

        if os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                current_app.logger.info(f"Current settings.json contents: {json.dumps(settings, indent=4)}")

            settings['image_human_name'] = new_image_human_name
            settings['image_template_name'] = new_image_template_name

            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=4)
                current_app.logger.info(f"Updated settings.json contents: {json.dumps(settings, indent=4)}")

            current_app.logger.info(f"Updated settings.json for image ID {image_id}.")
        else:
            current_app.logger.warning(f"settings.json not found for image ID {image_id} at path {settings_path}.")

        image.image_human_name = new_image_human_name
        image.image_template_name = new_image_template_name

        db.session.commit()
        current_app.logger.info(f"Image with ID {image_id} modified successfully.")

        return jsonify(success=True, message="Image and settings.json modified successfully")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error modifying image with ID {image_id}: {str(e)}")
        return jsonify(success=False, message="Error modifying image")

@blueprint.route('/settings/update_vmware_config', methods=['POST'])
@login_required
@admin_required
def update_vmware_config():
    esxi_ip = request.form.get('host_ip')
    vcenter_server = request.form.get('vcenter_server')
    vcenter_username = request.form.get('vcenter_username')
    vcenter_password = request.form.get('vcenter_password')

    config = ConfigModel.query.first()

    if config:
        if esxi_ip:
            config.set_esxi_ip(esxi_ip)
            config.set_esxi_host(esxi_ip)
            os.environ['ESXI_HOST'] = esxi_ip
        if vcenter_server:
            config.set_vcenter_server(vcenter_server)
            os.environ['VCENTER_SERVER'] = vcenter_server
        if vcenter_username:
            config.set_vcenter_username(vcenter_username)
            os.environ['VCENTER_USERNAME'] = vcenter_username
        if vcenter_password:
            config.set_vcenter_password(vcenter_password)
            os.environ['VCENTER_PASSWORD'] = vcenter_password
        db.session.commit()
        log_json('INFO', 'VMware configuration updated', esxi_ip=esxi_ip, vcenter_server=vcenter_server)
        flash('VMware configuration updated successfully!', 'success')
    else:
        log_json('ERROR', 'VMware configuration update failed')
        flash('VMware configuration update failed.', 'error')

    return redirect(url_for('settings_blueprint.settings_vmware'))

@blueprint.route('/settings/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get(user_id)
    if request.method == 'POST':
        user.username = request.form['username']
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if new_password and confirm_password and new_password == confirm_password:
            user.password = generate_password_hash(new_password)

        db.session.commit()
        log_json('INFO', f'User {user.username} has been updated', user_id=user.id)
        flash(f'{user.username} has been updated.', 'success')
        return redirect(url_for('settings_blueprint.settings_users'))

    user_data = {
        'id': user.id,
        'username': user.username,
    }
    return jsonify(user_data), 200

@blueprint.route('/delete_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == 1:
        message = 'Cannot delete this user.'
        log_json('WARNING', 'Attempted to delete super admin user', user_id=user_id)
        return render_template('home/message.html', message=message)

    user = User.query.get(user_id)
    if not user:
        message = 'User not found'
        log_json('ERROR', 'User not found', user_id=user_id)
        return render_template('home/message.html', message=message)
    db.session.delete(user)
    db.session.commit()
    log_json('INFO', f'User {user.username} has been deleted', user_id=user.id)
    flash(f'{user.username} has been deleted.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/associate_user_group', methods=['POST'])
@login_required
@admin_required
def associate_user_group():
    user_id = request.form['user_id']
    group_id = request.form['group_id']
    user = User.query.get(user_id)
    group = Group.query.get(group_id)
    if group not in user.groups:
        user.groups.append(group)
        db.session.commit()
        log_json('INFO', f'User {user.username} associated with group {group.name}', user_id=user.id, group_id=group.id)
    flash(f'{user.username} has been associated with {group.name}.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/remove_user_from_group', methods=['POST'])
@login_required
@admin_required
def remove_user_from_group():
    user_id = request.form['user_id']
    group_id = request.form['group_id']
    user = User.query.get(user_id)
    group = Group.query.get(group_id)
    if user_id == 1 and group_id == 1:
        flash(f'{user.username} cannot be removed from the {group.name} group. This is the Super Administrator account.', 'error')
    elif group in user.groups:
        user.groups.remove(group)
        db.session.commit()
        log_json('INFO', f'User {user.username} removed from group {group.name}', user_id=user.id, group_id=group.id)
        flash(f'{user.username} has been removed from {group.name}.', 'success')
    else:
        flash(f'{user.username} is not in the group {group.name}.', 'error')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/create_group', methods=['POST'])
@login_required
@admin_required
def create_group():
    groupname = request.form['groupname']
    groupdescription = request.form['groupdescription']
    new_group = Group(name=groupname, description=groupdescription)
    db.session.add(new_group)
    db.session.commit()
    log_json('INFO', f'Group {groupname} created', group_id=new_group.id)
    flash(f'Group {groupname} has been created.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/edit_group/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit_group(id):
    group = Group.query.get(id)
    group.name = request.form['groupname']
    group.description = request.form['groupdescription']
    db.session.commit()
    log_json('INFO', f'Group {group.name} updated', group_id=group.id)
    flash(f'{group.name} Group has been updated.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/delete_group/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_group(id):
    if id in [1, 2]:
        flash('The selected group cannot be deleted.', 'error')
        log_json('WARNING', 'Attempted to delete protected group', group_id=id)
        return redirect(url_for('settings_blueprint.settings_users'))
    group = Group.query.get(id)
    db.session.delete(group)
    db.session.commit()
    log_json('INFO', f'Group {group.name} deleted', group_id=group.id)
    flash(f'{group.name} Group has been removed.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/create_user', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form['username']
    password = request.form['password']
    new_user = User(username=username, password=password)
    new_user.groups.append(Group.query.filter_by(id=2).first())
    db.session.add(new_user)
    db.session.commit()
    log_json('INFO', f'User {username} created', user_id=new_user.id)
    flash(f'User: {username} has been created.', 'success')
    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/settings/new_password', methods=['GET', 'POST'])
@login_required
def new_password():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if not current_user.check_password(old_password):
            flash(f'Incorrect old password. Please try again.', 'error')
            log_json('ERROR', 'Incorrect old password attempt', user_id=current_user.id)
        elif new_password != confirm_password:
            flash(f'New password and confirmation do not match. Please try again.', 'error')
            log_json('ERROR', 'New password and confirmation do not match', user_id=current_user.id)
        else:
            current_user.set_password(new_password)
            db.session.commit()
            log_json('INFO', 'Password updated successfully', user_id=current_user.id)
            flash(f'Password updated successfully.', 'success')

        return redirect(url_for('settings_blueprint.settings_general'))

    return redirect(url_for('settings_blueprint.settings_general'))

@blueprint.route('/settings/reset_password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get(user_id)
    if user:
        auto_generate = request.form.get('auto_generate')
        if auto_generate:
            new_password = generate_random_password()
        else:
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            if new_password != confirm_password:
                flash('Passwords do not match', 'error')
                return redirect(url_for('settings_blueprint.settings'))

        user.set_password(new_password)
        db.session.commit()
        log_json('INFO', f'Password for user {user.username} has been reset', user_id=user.id)
        flash('Password has been reset', 'success')
    else:
        log_json('ERROR', 'User not found', user_id=user_id)
        flash('User not found', 'error')

    return redirect(url_for('settings_blueprint.settings_users'))

@blueprint.route('/get_playbook/<image_id>')
@login_required
@admin_required
def get_playbook(image_id):
    image = VmImageModel.query.get(image_id)
    if not image:
        return jsonify({'success': False, 'message': 'Image not found'})

    if image.network_type == 'domain':
        base_folder = 'ansible-deploy-vm-domain'
    else:
        base_folder = 'ansible-deploy-vm'

    playbook_path = os.path.join('apps/plugins', base_folder, 'tasks', image.image_folder_name, 'main.yml')

    if os.path.exists(playbook_path):
        with open(playbook_path, 'r') as file:
            playbook_content = file.read()
        return jsonify({'success': True, 'playbook_content': playbook_content})
    else:
        return jsonify({'success': False, 'message': 'Playbook not found'})


@blueprint.route('/get_playbook_content', methods=['POST'])
@login_required
@admin_required
def get_playbook_content():
    playbook_path = request.json.get('playbook')

    if not playbook_path or not os.path.isfile(playbook_path):
        log_json('ERROR', 'Invalid playbook path', playbook_path=playbook_path)
        return jsonify({'error': 'Invalid playbook path'}), 400

    with open(playbook_path, 'r') as file:
        content = file.read()
    log_json('INFO', 'Playbook content retrieved', playbook_path=playbook_path)
    return jsonify({'content': content})

@blueprint.route('/save_playbook_content', methods=['POST'])
@login_required
@admin_required
def save_playbook_content():
    playbook_path = request.json.get('playbook')
    content = request.json.get('content')
    if not playbook_path or not content:
        log_json('ERROR', 'Invalid playbook path or content', playbook_path=playbook_path)
        return jsonify({'error': 'Invalid playbook path or content'}), 400

    with open(playbook_path, 'w') as file:
        file.write(content)
    log_json('INFO', 'Playbook content saved', playbook_path=playbook_path)
    return jsonify({'message': 'Playbook saved successfully'})

@blueprint.route('/backup', methods=['POST'])
@login_required
@admin_required
def backup():
    models = [ConfigModel, History, NonDomainModel, DomainModel, PluginModel, DefaultVmSettingsModel]

    def model_to_dict(instance):
        data = {c.name: getattr(instance, c.name) for c in instance.__table__.columns}
        sensitive_fields = [field for field in data if 'password' in field]
        for field in sensitive_fields:
            if field in data:
                data.pop(field)
        return data

    data = {}
    for model in models:
        model_data = []
        for item in model.query.all():
            item_dict = model_to_dict(item)
            model_data.append(item_dict)
        data[model.__name__.lower()] = model_data

    backup_path = os.path.abspath(os.path.join(current_app.root_path, 'backups'))
    if not os.path.exists(backup_path):
        os.makedirs(backup_path)

    backup_filename = f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    backup_filepath = os.path.join(backup_path, backup_filename)

    with open(backup_filepath, 'w') as backup_file:
        json.dump(data, backup_file, cls=CustomJSONEncoder)

    log_json('INFO', 'Backup created', backup_filepath=backup_filepath)
    return send_file(
        backup_filepath,
        as_attachment=True,
        download_name=backup_filename,
        mimetype='application/json'
    )

@blueprint.route('/import', methods=['POST'])
@login_required
@admin_required
def import_data():
    if 'backup_file' not in request.files:
        log_json('ERROR', 'No backup file provided')
        return jsonify({'error': 'No backup file provided'}), 400

    backup_file = request.files['backup_file']

    if backup_file.filename == '':
        log_json('ERROR', 'No selected file')
        return jsonify({'error': 'No selected file'}), 400

    data = json.load(backup_file)

    models = {
        'history': History,
        'user': User,
        'group': Group,
        'configmodel': ConfigModel,
        'nondomainmodel': NonDomainModel,
        'domainmodel': DomainModel,
        'pluginmodel': PluginModel,
        'defaultvmsettingsmodel': DefaultVmSettingsModel,
    }

    for model_name, model in models.items():
        model_data = data.get(model_name, [])
        for item_data in model_data:
            item_data.pop('id', None)
            if 'password' in item_data:
                item_data.pop('password')
            if 'message_flashed' in item_data:
                item_data.pop('message_flashed')

            if model == DomainModel and 'domain_admin_password' not in item_data:
                log_json('ERROR', f"Skipping domain model import due to missing password for item {item_data.get('name', 'unknown')}")
                continue

            if model in [ConfigModel, DefaultVmSettingsModel]:
                existing_item = model.query.get(1)
                if existing_item:
                    for key, value in item_data.items():
                        setattr(existing_item, key, value)
                    db.session.add(existing_item)
                else:
                    new_item = model(**item_data)
                    db.session.add(new_item)
            elif model == NonDomainModel:
                existing_item = model.query.filter_by(designation=item_data.get('designation')).first()
                if existing_item:
                    for key, value in item_data.items():
                        setattr(existing_item, key, value)
                    db.session.add(existing_item)
                else:
                    new_item = model(**item_data)
                    db.session.add(new_item)
            else:
                item = model(**item_data)
                db.session.add(item)

    db.session.commit()
    log_json('INFO', 'Import successful')
    return jsonify({'message': 'Import successful'}), 200


@blueprint.route('/clear-history', methods=['POST'])
@login_required
@admin_required
def clear_history():
    try:
        History.query.delete()
        db.session.commit()
        log_json('INFO', 'History cleared successfully')
        return jsonify({'message': 'History cleared successfully'}), 200
    except Exception as e:
        db.session.rollback()
        log_json('ERROR', 'Error clearing history', error=str(e))
        return jsonify({'error': 'An error occurred while clearing history'}), 500

@blueprint.route('/settings/update_default_vm_values', methods=['POST'])
@login_required
@admin_required
def update_default_vm_values():
    vm_state = request.form.get('vm_state')
    linux_disk_size = request.form.get('linux_disk_size')
    windows_disk_size = request.form.get('windows_disk_size')
    vm_hw_scsi = request.form.get('vm_hardware_scsi')
    vm_type = request.form.get('vm_type')
    linux_template_username = request.form.get('linux_template_username')
    windows_template_username = request.form.get('windows_template_username')

    defaultvmsettings = DefaultVmSettingsModel.query.first()

    os.environ['VM_STATE'] = vm_state
    os.environ['LINUX_DISK_SIZE'] = linux_disk_size
    os.environ['WINDOWS_DISK_SIZE'] = windows_disk_size
    os.environ['VM_HW_SCSI'] = vm_hw_scsi
    os.environ['VM_TYPE'] = vm_type
    os.environ['LINUX_TEMPLATE_USERNAME'] = linux_template_username
    os.environ['WINDOWS_TEMPLATE_USERNAME'] = windows_template_username

    if defaultvmsettings:
        defaultvmsettings.set_vm_state(vm_state)
        defaultvmsettings.set_linux_disk_size(linux_disk_size)
        defaultvmsettings.set_windows_disk_size(windows_disk_size)
        defaultvmsettings.set_vm_hw_scsi(vm_hw_scsi)
        defaultvmsettings.set_vm_type(vm_type)
        defaultvmsettings.set_linux_template_username(linux_template_username)
        defaultvmsettings.set_windows_template_username(windows_template_username)
        db.session.commit()
        log_json('INFO', 'Default VM values updated', vm_state=vm_state)
        flash('Default VM values updated successfully!', 'success')
    else:
        log_json('ERROR', 'Default VM values update failed')
        flash('Default VM values update failed.', 'error')

    return redirect(url_for('settings_blueprint.settings_default_vm'))

@blueprint.route('/settings/update_template_passwords', methods=['POST'])
@login_required
@admin_required
def update_template_passwords():
    linux_template_password = request.form.get('linux_template_password')
    windows_template_password = request.form.get('windows_template_password')

    defaultvmsettings = DefaultVmSettingsModel.query.first()

    os.environ['LINUX_TEMPLATE_PASSWORD'] = linux_template_password
    os.environ['WINDOWS_TEMPLATE_PASSWORD'] = windows_template_password

    if defaultvmsettings:
        if linux_template_password:
            defaultvmsettings.set_linux_template_password(linux_template_password)
        if windows_template_password:
            defaultvmsettings.set_windows_template_password(windows_template_password)
        db.session.commit()
        log_json('INFO', 'Template passwords updated')
        flash('Passwords updated successfully!', 'success')
    else:
        log_json('ERROR', 'Password update failed')
        flash('Password update failed.', 'error')

    return redirect(url_for('settings_blueprint.settings_default_vm'))

@blueprint.route('/get_backup_history', methods=['GET'])
@login_required
@admin_required
def get_backup_history():
    backup_folder = os.path.abspath(os.path.join(current_app.root_path, 'backups'))
    backup_history = []

    try:
        for filename in os.listdir(backup_folder):
            backup_history.append(filename)
        log_json('INFO', 'Backup history retrieved')
    except FileNotFoundError:
        log_json('ERROR', 'Backup folder not found')
        pass

    return jsonify(backup_history)

@blueprint.route('/download_backup/<filename>', methods=['GET'])
@login_required
@admin_required
def download_backup(filename):
    backup_folder = os.path.abspath(os.path.join(current_app.root_path, 'backups'))

    if not filename.startswith('..') and '/' not in filename:
        log_json('INFO', 'Downloaded backup file', filename=filename)
        return send_from_directory(backup_folder, filename, as_attachment=True)
    else:
        abort(404)

@blueprint.route('/remove_backup/<filename>', methods=['DELETE'])
@login_required
@admin_required
def remove_backup(filename):
    backup_folder = os.path.abspath(os.path.join(current_app.root_path, 'backups'))
    backup_path = os.path.join(backup_folder, filename)

    try:
        os.remove(backup_path)
        log_json('INFO', 'Backup removed', filename=filename)
        return jsonify({'message': f'Successfully removed backup: {filename}'}), 200
    except FileNotFoundError:
        log_json('ERROR', 'Backup not found', filename=filename)
        return jsonify({'error': f'Backup not found: {filename}'}), 404
    except Exception as e:
        log_json('ERROR', 'Error removing backup', error=str(e))
        return jsonify({'error': f'Error removing backup: {str(e)}'}), 500

@blueprint.context_processor
def inject_non_domain_model_data():
    return {'non_domain_model_data': NonDomainModel.query.all()}

@blueprint.context_processor
def inject_domain_model_data():
    return {'domain_model_data': DomainModel.query.all()}

@blueprint.route('/delete_non_domain_item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def delete_non_domain_item(item_id):
    non_domain_item = NonDomainModel.query.get(item_id)
    if non_domain_item:
        db.session.delete(non_domain_item)
        db.session.commit()
        log_json('INFO', 'Non-Domain item deleted successfully', item_id=item_id)
        flash("Non-Domain item deleted successfully", "success")
    else:
        log_json('ERROR', 'Non-Domain item not found', item_id=item_id)
        flash("Non-Domain item not found", "error")
    return redirect(url_for('home_blueprint.home'))

@blueprint.route('/delete_domain_item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def delete_domain_item(item_id):
    domain_item = DomainModel.query.get(item_id)
    if domain_item:
        db.session.delete(domain_item)
        db.session.commit()
        log_json('INFO', 'Domain item deleted successfully', item_id=item_id)
        flash("Domain item deleted successfully", "success")
    else:
        log_json('ERROR', 'Domain item not found', item_id=item_id)
        flash("Domain item not found", "error")
    return redirect(url_for('home_blueprint.home'))
