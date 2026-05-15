"""Trusted-header auth when library runs behind the dashboard nginx."""

from flask import current_app, request

from .models import User, db


def is_proxy_mode() -> bool:
    return bool(current_app.config.get("AUTH_PROXY_HEADER"))


def load_user_from_proxy_header() -> User | None:
    """Resolve the user from the trusted proxy header, auto-provisioning on first sight."""
    header = current_app.config.get("AUTH_PROXY_HEADER")
    if not header:
        return None
    username = request.headers.get(header)
    if not username:
        return None
    return get_or_create_proxy_user(username)


def get_or_create_proxy_user(username: str) -> User:
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, password_hash=None)
        db.session.add(user)
        db.session.commit()
    return user
