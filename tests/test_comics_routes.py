import io
from datetime import date, timedelta

import pytest

from library import settings
from library.comics import providers
from library.comics.models import ComicIssue, ComicProgress, ComicSeries
from library.downloads.models import DOWNLOADED, SKIPPED, WANTED
from library.models import db
from tests.conftest import make_cbz


class FakeProvider:
    name = "comicvine"

    def search_series(self, query):
        return [{"provider": "comicvine", "provider_id": "49901", "name": "Saga", "start_year": 2012, "publisher": "Image", "volume": None, "description": "", "cover_url": None, "issue_count": 3, "cv_id": 49901, "metron_id": None}]

    def get_series(self, provider_id):
        return self.search_series("")[0]

    def get_issues(self, provider_id):
        today = date.today()
        return [
            {"provider_id": "1", "number": "1", "cover_date": today - timedelta(days=400)},
            {"provider_id": "2", "number": "2", "cover_date": today - timedelta(days=30)},
            {"provider_id": "3", "number": "3", "store_date": today + timedelta(days=5)},
        ]


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("library.comics.series.get_provider", lambda name=None: fake)
    monkeypatch.setattr(providers, "get_provider", lambda name=None: fake)
    monkeypatch.setattr(providers, "available", lambda: ["comicvine"])
    return fake


@pytest.fixture
def saga(app, comic_dir, admin_client, provider):
    from library.comics.series import refresh_series

    response = admin_client.post("/comics/api/series", json={"provider": "comicvine", "provider_id": "49901", "monitor": "future"})
    assert response.status_code == 201
    series = ComicSeries.query.one()
    # Following answers at once; the worker fetches the issues.
    assert admin_client.get(f"/comics/api/series/{series.id}").get_json()["pending"] is True
    refresh_series(series)
    assert admin_client.get(f"/comics/api/series/{series.id}").get_json() == {"pending": False, "issues": 3}
    return series


def test_comics_need_sign_in(client, comic_dir):
    assert client.get("/comics/").status_code in (302, 401)
    assert client.get("/api/import").status_code == 401
    assert client.get("/get").status_code in (302, 401)
    assert client.put("/comics/api/issues/1/progress", json={"page": 1}).status_code == 401


def test_every_page_renders(admin_client, saga, tmp_path, comic_dir):
    issue = saga.issues[0]
    from library.comics import files

    files.import_file(str(make_cbz(tmp_path / "Saga 001.cbz")), issue)
    for path in ["/comics/", "/get?q=saga", f"/comics/series/{saga.id}", "/downloads", "/settings", f"/comics/read/{issue.id}"]:
        response = admin_client.get(path)
        assert response.status_code == 200, path
    assert b"Saga" in admin_client.get("/comics/").data
    downloads = admin_client.get("/downloads").data.decode()
    assert "Import" in downloads and "Coming up" not in downloads and "Background jobs" not in downloads


def test_empty_comics_page_says_what_to_do(admin_client, comic_dir):
    page = admin_client.get("/comics/").data.decode()
    assert "No series yet" in page and 'href="/get"' in page
    assert 'href="/settings"' in page and 'href="/downloads"' in page


def _series_with_one_file(comic_dir, tmp_path):
    """A series with #1 on disk and #2 missing, made without the API."""
    from library.comics import files

    s = ComicSeries(provider="local", provider_id="saga", name="Saga", monitor="none")
    have = ComicIssue(series=s, number="1", sort_number=1, status=SKIPPED)
    missing = ComicIssue(series=s, number="2", sort_number=2, status=WANTED, title="Not here")
    empty = ComicSeries(provider="local", provider_id="empty", name="Nothing Yet", monitor="none")
    db.session.add_all([s, have, missing, empty])
    db.session.commit()
    files.import_file(str(make_cbz(tmp_path / "Saga 001.cbz", pages=4)), have)
    return s, have, missing


def test_readers_see_only_what_there_is_to_read(standard_client, comic_dir, tmp_path, standard_user):
    s, have, missing = _series_with_one_file(comic_dir, tmp_path)
    page = standard_client.get("/comics/").data.decode()
    assert "Saga" in page and "Nothing Yet" not in page
    # No Get, Downloads or Settings.
    assert 'href="/get"' not in page and 'href="/downloads"' not in page and 'href="/settings"' not in page
    series = standard_client.get(f"/comics/series/{s.id}").data.decode()
    assert "Not here" not in series and "Stop following" not in series and "selectToggle" not in series
    # The cover opens #1, and once they're partway in, the wall opens on
    # Reading and the cover picks up where they left off.
    assert f'href="/comics/read/{have.id}" aria-label="Read Saga #1"' in page
    assert standard_client.get(f"/comics/read/{have.id}").status_code == 200
    assert standard_client.put(f"/comics/api/issues/{have.id}/progress", json={"page": 1}).status_code == 200
    page = standard_client.get("/comics/").data.decode()
    assert 'aria-label="Continue Saga #1"' in page and "#1 · 50%" in page and 'role="radiogroup"' not in page
    assert standard_client.get(f"/comics/issue/{have.id}/download").status_code == 200


@pytest.mark.parametrize("path, home", [("/get", "/"), ("/downloads", "/"), ("/settings", "/")])
def test_admin_pages_send_readers_home(standard_client, comic_dir, path, home):
    response = standard_client.get(path)
    assert response.status_code == 302 and response.location.endswith(home)
    assert 'href="/settings"' not in standard_client.get(home).data.decode()


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/get/search/books?q=saga"),
        ("get", "/api/get/search/comics?q=saga"),
        ("post", "/api/get/books"),
        ("post", "/comics/api/series"),
        ("patch", "/comics/api/series/1"),
        ("post", "/comics/api/series/1/search"),
        ("patch", "/comics/api/issues/1"),
        ("post", "/api/wanted/comic/1/search"),
        ("get", "/api/wanted/book/1/releases"),
        ("post", "/comics/api/issues/1/upload"),
        ("get", "/api/import"),
        ("post", "/api/import/scan"),
        ("get", "/api/downloads"),
        ("post", "/api/jobs/search"),
        ("post", "/api/downloads/1/retry"),
        ("get", "/api/settings"),
    ],
)
def test_managing_is_admin_only(standard_client, comic_dir, method, path):
    assert getattr(standard_client, method)(path).status_code == 403


def test_follow_series_wants_whats_coming(saga):
    assert [i.status for i in saga.issues] == [SKIPPED, SKIPPED, WANTED]


def test_get_search_marks_followed_series(admin_client, saga, monkeypatch):
    from library.books import openlibrary

    monkeypatch.setattr(openlibrary, "search", lambda q: [])
    assert admin_client.get("/api/get/search/comics?q=saga").get_json()["results"][0]["followed_id"] == saga.id
    assert admin_client.get("/api/get/search/books?q=saga").get_json()["results"] == []


def test_get_search_without_a_comics_provider_still_finds_books(admin_client, comic_dir, monkeypatch):
    from library.books import openlibrary

    monkeypatch.setattr(openlibrary, "search", lambda q: [{"ol_key": "/works/OL1W", "title": "Saga", "author": "Someone", "year": 2001, "cover_url": None}])
    books = admin_client.get("/api/get/search/books?q=saga").get_json()
    assert books["results"][0]["status"] is None and books["error"] is None
    monkeypatch.setattr(providers, "available", lambda: [])
    assert "Settings" in admin_client.get("/api/get/search/comics?q=saga").get_json()["error"]


def test_monitor_all_and_bulk(admin_client, saga):
    assert admin_client.patch(f"/comics/api/series/{saga.id}", json={"monitor": "all"}).get_json() == {"monitor": "all", "wanted": 3}
    assert all(i.status == WANTED for i in saga.issues)
    ids = [i.id for i in saga.issues]
    assert admin_client.post("/comics/api/issues/bulk", json={"ids": ids, "status": "skipped"}).get_json()["changed"] == 3


def test_upload_to_import_folder_matches_and_files(admin_client, saga, comic_dir):
    data = {"files": [(io.BytesIO(make_cbz(comic_dir / "tmp.cbz").read_bytes()), "Saga 002 (2024) (Digital).cbz"), (io.BytesIO(b"x"), "notes.txt")]}
    result = admin_client.post("/api/import/upload", data=data, content_type="multipart/form-data").get_json()
    assert len(result["imported"]) == 1
    assert saga.issues[1].status == DOWNLOADED


def test_manual_import_into_a_new_local_series(admin_client, comic_dir):
    inbox = comic_dir / "_import"
    inbox.mkdir()
    make_cbz(inbox / "Zine 004 (2021).cbz")
    listing = admin_client.get("/api/import").get_json()
    assert listing["files"][0]["reason"].startswith("No followed series")
    response = admin_client.post("/api/import/file", json={"path": "Zine 004 (2021).cbz", "new_series": "Zine"})
    assert response.status_code == 200
    series = ComicSeries.query.one()
    assert series.provider == "local" and series.issues[0].number == "4" and series.issues[0].status == DOWNLOADED


def test_import_refuses_paths_outside_the_folder(admin_client, comic_dir):
    response = admin_client.post("/api/import/file", json={"path": "../../etc/passwd", "new_series": "x"})
    assert response.status_code == 404


def test_reading_pages_and_progress(admin_client, saga, tmp_path, admin_user):
    from library.comics import files

    issue = saga.issues[0]
    files.import_file(str(make_cbz(tmp_path / "Saga 001.cbz", pages=4)), issue)
    page = admin_client.get(f"/comics/issue/{issue.id}/page/1")
    assert page.status_code == 200 and page.mimetype == "image/webp"
    assert admin_client.get(f"/comics/issue/{issue.id}/page/9").status_code == 404
    assert admin_client.get(f"/comics/issue/{issue.id}/cover?w=300").mimetype == "image/webp"

    admin_client.put(f"/comics/api/issues/{issue.id}/progress", json={"page": 2})
    assert b'data-page="2"' in admin_client.get(f"/comics/read/{issue.id}").data
    admin_client.put(f"/comics/api/issues/{issue.id}/progress", json={"page": 3})
    progress = ComicProgress.query.filter_by(user_id=admin_user.id, issue_id=issue.id).one()
    assert progress.finished


def test_delete_file_is_admin_only(standard_client, comic_dir, tmp_path):
    s = ComicSeries(provider="local", provider_id="x", name="X")
    i = ComicIssue(series=s, number="1", sort_number=1, status=DOWNLOADED, filename="x.cbz")
    db.session.add_all([s, i])
    db.session.commit()
    assert standard_client.delete(f"/comics/api/issues/{i.id}/file").status_code == 403


def test_settings_keep_masked_secrets(admin_client, comic_dir):
    settings.set_many({"comicvine_api_key": "abcdef1234567890"})
    shown = admin_client.get("/api/settings").get_json()
    shown["max_size_mb"] = 300
    shown["rejected_words"] = "c2c, preview"
    shown["indexers"] = [{"name": "Geek", "url": "https://api.nzbgeek.info", "api_key": "secret-key-123", "kind": "newznab"}]
    saved = admin_client.put("/api/settings", json=shown).get_json()
    assert settings.get("comicvine_api_key") == "abcdef1234567890"
    assert settings.get("max_size_mb") == 300 and settings.get("rejected_words") == ["c2c", "preview"]
    # Saving again with the masked key keeps the real one.
    admin_client.put("/api/settings", json=saved)
    assert settings.get("indexers")[0]["api_key"] == "secret-key-123"


def test_search_without_indexers_says_so(admin_client, saga):
    response = admin_client.post(f"/api/wanted/comic/{saga.issues[1].id}/search")
    assert response.status_code == 400 and "indexer" in response.get_json()["error"]


def test_books_page_links_to_comics(admin_client):
    assert b"/comics/" in admin_client.get("/").data


def test_settings_tests_use_the_form_without_saving(admin_client, comic_dir, tmp_path):
    folder = tmp_path / "hole"
    folder.mkdir()
    response = admin_client.post("/api/settings/test", json={"what": "blackhole", "values": {"blackhole_dir": str(folder)}})
    assert response.status_code == 200, response.get_json()
    assert settings.get("blackhole_dir") == ""
    # A masked key on the form stands for the saved one.
    settings.set_many({"sabnzbd": {"url": "", "api_key": "saved-key-1234", "category": "comics", "book_category": "books"}})
    response = admin_client.post("/api/settings/test", json={"what": "sabnzbd", "values": {"url": "", "api_key": settings.masked("saved-key-1234")}})
    assert response.status_code == 502 and "isn't set up" in response.get_json()["error"]


def test_settings_page_is_shared_and_admin_only(admin_client, comic_dir):
    page = admin_client.get("/settings").data.decode()
    assert "for books and comics" in page and 'id="comics"' in page
    assert 'href="/settings"' in admin_client.get("/").data.decode()


def test_readers_get_issue_covers_they_can_mark_read(standard_client, comic_dir, tmp_path):
    s, have, missing = _series_with_one_file(comic_dir, tmp_path)
    page = standard_client.get(f"/comics/series/{s.id}").data.decode()
    assert 'id="issueWall"' in page and "Up next" in page and ">Read #1<" in page
    assert standard_client.put(f"/comics/api/issues/{have.id}/progress", json={"page": 3, "finished": True}).get_json()["finished"]
    page = standard_client.get(f"/comics/series/{s.id}").data.decode()
    # Read shows in the caption, as a book's progress does; nothing floats over the cover but ⋯.
    assert "is-read" in page and "author\">Read</span>" in page and "cover-flag" not in page and "toggle-read" not in page
    assert standard_client.put(f"/comics/api/issues/{have.id}/progress", json={"page": 0, "finished": False}).get_json() == {"page": 0, "finished": False}


def test_wanted_is_grouped_by_series(admin_client, saga):
    admin_client.patch(f"/comics/api/series/{saga.id}", json={"monitor": "all"})
    page = admin_client.get("/downloads").data.decode()
    assert page.count('class="entry-group"') == 1 and "#2, #1" in page


def test_comic_date():
    from library.comics.routes import comic_date

    this_year = date.today().year
    assert comic_date(date(this_year, 8, 19)) == "19 Aug"
    assert comic_date("2019-03-05") == "5 Mar 2019"
    assert comic_date(None) == ""
