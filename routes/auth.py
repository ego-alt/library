from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash
from models import User

auth = Blueprint('auth', __name__, url_prefix='/auth')


@auth.route('/login', methods=['POST'])
def login_post():
    username = request.form.get('username')
    password = request.form.get('password')
    remember = True if request.form.get('remember') else False

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid username or password'}), 401

    login_user(user, remember=remember)
    return jsonify({
        'success': True,
        'username': user.username,
        'role': user.role
    })

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index_routes.index')) 