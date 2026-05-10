"""Smoke tests for create_app() configuration & validation."""

from library import create_app


def test_create_app_uses_test_default_when_testing(monkeypatch, tmp_path):
    """Tests get a deterministic fallback so they don't need to set the env var."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(tmp_path),
    })
    assert app.config["SECRET_KEY"]


def test_create_app_falls_back_to_random_key_with_warning(monkeypatch, tmp_path, caplog):
    """If SECRET_KEY isn't set in non-test mode, generate a random one and warn."""
    import logging

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="library"):
        app = create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_DIR": str(tmp_path),
        })
    assert app.config["SECRET_KEY"]
    assert any("SECRET_KEY" in rec.message for rec in caplog.records)


def test_create_app_honors_explicit_secret_key(tmp_path):
    """An explicit SECRET_KEY in config_overrides wins over the env-var path."""
    app = create_app({
        "SECRET_KEY": "from-overrides",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(tmp_path),
    })
    assert app.config["SECRET_KEY"] == "from-overrides"
