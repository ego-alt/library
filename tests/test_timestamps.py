"""Every timestamp is stored as UTC and read back with its zone, so the times
sent to the browser end in +00:00 (one without a zone is read as local)."""
from sqlalchemy import DateTime

from library.models import db


def test_every_timestamp_column_is_utc():
    plain = [f"{t.name}.{c.name}" for t in db.metadata.tables.values() for c in t.columns if isinstance(c.type, DateTime)]
    assert plain == []


def test_times_reach_the_browser_with_their_zone(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_json()["created_at"].endswith("+00:00")
