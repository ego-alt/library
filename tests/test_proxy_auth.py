def test_proxy_header_auto_provisions_user(app, client):
    app.config["AUTH_PROXY_HEADER"] = "X-Forwarded-User"
    from library.models import User, db

    r = client.get("/", headers={"X-Forwarded-User": "ellery"})
    assert r.status_code == 200
    user = User.query.filter_by(username="ellery").one()
    assert user.password_hash is None


def test_proxy_login_redirects_to_dashboard(app, client):
    app.config["AUTH_PROXY_HEADER"] = "X-Forwarded-User"
    r = client.post("/auth/login", data={"username": "x", "password": "y"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")


def test_proxy_logout_redirects_to_dashboard_logout(app, client):
    app.config["AUTH_PROXY_HEADER"] = "X-Forwarded-User"
    r = client.get("/auth/logout")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/logout")


def test_healthz_is_unauthenticated(app, client):
    r = client.get("/healthz")
    assert r.status_code == 200
