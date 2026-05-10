def test_login_succeeds_with_correct_password(client, standard_user):
    r = client.post("/auth/login", data={"username": "standard", "password": "pw"})
    assert r.status_code == 200
    assert r.get_json()["success"] is True
    assert r.get_json()["username"] == "standard"


def test_login_rejects_wrong_password(client, standard_user):
    r = client.post("/auth/login", data={"username": "standard", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid" in r.get_json()["error"]


def test_login_rejects_unknown_user(client):
    r = client.post("/auth/login", data={"username": "ghost", "password": "pw"})
    assert r.status_code == 401


def test_logout_redirects(client, standard_client):
    # standard_client is already logged in via session injection
    r = standard_client.get("/auth/logout")
    assert r.status_code in (200, 302)


# --- decorators -----------------------------------------------------------------


def test_login_required_endpoints_reject_anonymous(client, book):
    # /upload_book is @json_login_required
    r = client.post("/upload_book")
    assert r.status_code == 401
    assert r.get_json()["error"] == "Authentication required"


def test_admin_required_endpoint_rejects_standard(standard_client, book):
    r = standard_client.delete(f"/book/{book.filename}")
    assert r.status_code == 403
    assert "Admin" in r.get_json()["error"]


def test_admin_required_endpoint_rejects_anonymous(client, book):
    r = client.delete(f"/book/{book.filename}")
    assert r.status_code == 401
