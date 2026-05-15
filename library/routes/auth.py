from flask import Blueprint, current_app, jsonify, redirect, request, url_for
from flask_login import current_user, login_user, logout_user

from ..models import User
from ..proxy_auth import is_proxy_mode

auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.route("/login", methods=["POST"])
def login():
    if is_proxy_mode():
        return redirect("/", code=302)

    username = request.form.get("username")
    password = request.form.get("password")
    remember = True if request.form.get("remember") else False

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid username or password"}), 401

    login_user(user, remember=remember)
    return jsonify({"success": True, "username": user.username, "role": user.role})


@auth.route("/logout")
def logout():
    if is_proxy_mode():
        return redirect("/logout", code=302)
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("index_routes.index"))
