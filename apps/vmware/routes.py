from datetime import datetime
from functools import wraps
import logging
from threading import Lock
import os
import json
from werkzeug.security import generate_password_hash
from apps.config import Config
from apps.vmware import blueprint
from apps.models import ConfigModel
from apps import db
from flask_login import login_required, current_user
from flask import current_app, Response, send_file, abort
from flask import jsonify, render_template, redirect, request, session, url_for
from flask import flash
import urllib.request
import base64
import requests
from retrying import retry
from time import sleep

vcenter_session_id = None
auth_lock = Lock()

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or 1 not in [group.id for group in current_user.groups]:
            return render_template('error/403.html'), 403
        return func(*args, **kwargs)
    return decorated_view

@retry(stop_max_attempt_number=3, wait_fixed=1000)
def make_request(url, headers, resource_name):
    response = requests.get(url, headers=headers, verify=False)

    if response.status_code == 200:
        return response.json()
    else:
        raise ValueError(f'Failed to retrieve {resource_name} (HTTP {response.status_code})')

def setup_auth():
    global vcenter_session_id

    config = ConfigModel.query.get(1)
    if config and config.vcenter_server:
        try:
            vcenter_auth_url = f'https://{config.vcenter_server}/rest/com/vmware/cis/session'
            api_user = config.vcenter_username
            api_pass = config.get_vcenter_password()

            with auth_lock:
                if vcenter_session_id is None:
                    auth_response = requests.post(vcenter_auth_url, auth=(api_user, api_pass), verify=False)

                    if auth_response.status_code == 200:
                        vcenter_session_id = auth_response.json().get("value")
        except Exception as e:
            print(f"An error occurred during authentication setup: {str(e)}")

def cleanup_auth(response):
    global vcenter_session_id

    with auth_lock:
        pass

    return response

blueprint.before_request(setup_auth)

blueprint.after_request(cleanup_auth)

@blueprint.route('/get_vcenter_data', methods=['GET'])
@login_required
@admin_required
def get_vcenter_data():
    global vcenter_session_id

    config = ConfigModel.query.get(1)

    if config and config.vcenter_server:
        try:
            vcenter_auth_url = f'https://{config.vcenter_server}/rest/com/vmware/cis/session'
            api_urls = {
                'datastores': f'https://{config.vcenter_server}/api/vcenter/datastore',
                'datacenters': f'https://{config.vcenter_server}/api/vcenter/datacenter',
                'vm_folders': f'https://{config.vcenter_server}/api/vcenter/folder',
                'vm_networks': f'https://{config.vcenter_server}/api/vcenter/network',
            }
            
            api_user = config.vcenter_username
            api_pass = config.get_vcenter_password()

            with auth_lock:
                max_retries_auth = 3
                for attempt_auth in range(max_retries_auth):
                    try:
                        auth_response = requests.post(vcenter_auth_url, auth=(api_user, api_pass), verify=False)

                        if auth_response.status_code == 200:
                            vcenter_session_id = auth_response.json().get("value")
                            break
                        else:
                            sleep(1)
                    except requests.exceptions.RequestException as e:
                        print(f"Authentication attempt {attempt_auth + 1} failed: {e}")

                        sleep(1)

                if not vcenter_session_id:
                    return jsonify({'error': f'Failed to obtain session ID after {max_retries_auth} attempts'}), 500

            headers = {'vmware-api-session-id': vcenter_session_id}

            vcenter_data = {}

            for resource, url in api_urls.items():
                try:
                    data = make_request(url, headers, resource)
                    vcenter_data[resource] = data
                except ValueError as e:
                    return jsonify({'error': str(e)}), 500

            return jsonify(vcenter_data)

        except Exception as e:
            error_message = str(e)
            print(f"An error occurred: {error_message}")
            return jsonify({'error': 'An error occurred while fetching vCenter data. Check the logs for details.'}), 500
    else:
        return jsonify({'error': 'vCenter Server not configured'}), 404