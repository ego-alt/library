"""Smoke tests for create_app() configuration & validation."""

import pytest

from library import BOOK_DIR_SENTINEL, create_app


@pytest.fixture
def marked_book_dir(tmp_path):
    """A tmp BOOK_DIR with the mount sentinel, for non-TESTING boots."""
    (tmp_path / BOOK_DIR_SENTINEL).touch()
    return tmp_path


def test_create_app_uses_test_default_when_testing(monkeypatch, tmp_path):
    """Tests get a deterministic fallback so they don't need to set the env var."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(tmp_path),
    })
    assert app.config["SECRET_KEY"]


def test_create_app_falls_back_to_random_key_with_warning(monkeypatch, marked_book_dir, caplog):
    """If SECRET_KEY isn't set in non-test mode, generate a random one and warn."""
    import logging

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="library"):
        app = create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_DIR": str(marked_book_dir),
        })
    assert app.config["SECRET_KEY"]
    assert any("SECRET_KEY" in rec.message for rec in caplog.records)


def test_create_app_honors_explicit_secret_key(marked_book_dir):
    """An explicit SECRET_KEY in config_overrides wins over the env-var path."""
    app = create_app({
        "SECRET_KEY": "from-overrides",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(marked_book_dir),
    })
    assert app.config["SECRET_KEY"] == "from-overrides"


def test_create_app_refuses_unmarked_book_dir(monkeypatch, tmp_path):
    """Without the sentinel file, boot must fail loudly (the original incident)."""
    monkeypatch.setenv("SECRET_KEY", "x")
    with pytest.raises(RuntimeError, match="sentinel"):
        create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_DIR": str(tmp_path),
        })


def test_create_app_refuses_missing_book_dir(monkeypatch, tmp_path):
    """Without BOOK_DIR itself, boot must fail loudly too."""
    monkeypatch.setenv("SECRET_KEY", "x")
    missing = tmp_path / "not-mounted"
    with pytest.raises(RuntimeError, match="does not exist"):
        create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_DIR": str(missing),
        })
