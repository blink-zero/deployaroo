import logging
from datetime import datetime
from flask import Blueprint, redirect, render_template, request, url_for, session
from flask_login import login_user, logout_user, login_required, current_user
from apps.auth import blueprint
from apps.models import User
from apps.utils.logging import log_json

@blueprint.route('/', methods=['GET', 'POST'])
@blueprint.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        username = request.form['user_id']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            error = 'Invalid username or password'
            log_json('WARNING', 'Failed login attempt', username=username)
        else:
            login_user(user)
            session['username'] = user.username
            log_json('INFO', 'User logged in', username=user.username)
            return redirect(url_for('home_blueprint.home'))

    return render_template('accounts/login.html', error=error)

@blueprint.route('/logout')
@login_required
def logout():
    username = session.get('username', 'anonymous')
    logout_user()
    log_json('INFO', 'User logged out', username=username)
    session.pop('username', None)
    return redirect(url_for('auth_blueprint.login'))
