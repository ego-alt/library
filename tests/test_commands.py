"""Tests for Flask CLI commands."""

import sqlite3

import pytest
from click.testing import CliRunner

from library import BOOK_DIR_SENTINEL, create_app
from library.commands import backup_db_command
from library.models import Book, db


@pytest.fixture
def file_backed_app(tmp_path, monkeypatch):
    """An app with an on-disk SQLite DB so backup-db has something real to copy."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    book_dir = tmp_path / "books"
    book_dir.mkdir()
    (book_dir / BOOK_DIR_SENTINEL).touch()
    db_path = tmp_path / "library.db"
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "BOOK_DIR": str(book_dir),
    })
    with app.app_context():
        db.create_all()
        db.session.add(
            Book(
                title="X",
                author="Y",
                filename="x.epub",
                cover_path="OEBPS/cover.png",
                access_level="standard",
            )
        )
        db.session.commit()
    return app, str(db_path)


def test_backup_db_writes_a_usable_copy(file_backed_app, tmp_path):
    app, _ = file_backed_app
    dest = tmp_path / "backups"
    runner = CliRunner()
    with app.app_context():
        result = runner.invoke(backup_db_command, ["--to", str(dest)])
    assert result.exit_code == 0, result.output

    written = [p for p in dest.iterdir() if p.name.startswith("library-")]
    assert len(written) == 1
    # The backup should be a real SQLite DB carrying the row we inserted.
    with sqlite3.connect(written[0]) as conn:
        rows = conn.execute("SELECT title FROM books").fetchall()
    assert rows == [("X",)]


def test_backup_db_rotates_to_keep(file_backed_app, tmp_path):
    app, _ = file_backed_app
    dest = tmp_path / "backups"
    dest.mkdir()
    # Plant older fake backups so we can verify rotation without time-mocking.
    for ts in ("20240101-000000", "20240102-000000", "20240103-000000"):
        (dest / f"library-{ts}.db").write_bytes(b"fake")

    runner = CliRunner()
    with app.app_context():
        result = runner.invoke(backup_db_command, ["--to", str(dest), "--keep", "2"])
    assert result.exit_code == 0, result.output

    remaining = sorted(p.name for p in dest.iterdir() if p.name.startswith("library-"))
    assert len(remaining) == 2
    # The two newest survive: today's fresh backup plus the latest planted one.
    assert "library-20240103-000000.db" in remaining
    assert "library-20240101-000000.db" not in remaining
    assert "library-20240102-000000.db" not in remaining


def test_backup_db_refuses_in_memory_database(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    book_dir = tmp_path / "books"
    book_dir.mkdir()
    (book_dir / BOOK_DIR_SENTINEL).touch()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(book_dir),
    })
    runner = CliRunner()
    with app.app_context():
        result = runner.invoke(backup_db_command, ["--to", str(tmp_path / "backups")])
    assert result.exit_code != 0
    assert "in-memory" in result.output


def test_backup_db_ignores_unrelated_files_when_rotating(file_backed_app, tmp_path):
    """Files that don't match the library-*.db naming are left alone."""
    app, _ = file_backed_app
    dest = tmp_path / "backups"
    dest.mkdir()
    (dest / "README").write_text("hands off")
    (dest / "library-2024.db").write_bytes(b"non-matching name")

    runner = CliRunner()
    with app.app_context():
        result = runner.invoke(backup_db_command, ["--to", str(dest), "--keep", "1"])
    assert result.exit_code == 0, result.output

    assert (dest / "README").exists()
    assert (dest / "library-2024.db").exists()
