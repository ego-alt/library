import io
from datetime import date, timedelta

import pytest

from library.comics import providers, settings
from library.comics.models import DOWNLOADED, SKIPPED, WANTED, ComicIssue, ComicProgress, ComicSeries
from library.models import db
from tests.conftest import make_cbz


class FakeProvider:
    name = "comicvine"

    def search_series(self, query):
        return [
            {
                "provider": "comicvine",
                "provider_id": "49901",
                "name": "Saga",
                "start_year": 2012,
                "publisher": "Image",
                "volume": None,
                "description": "",
                "cover_url": None,
                "issue_count": 3,
                "cv_id": 49901,
                "metron_id": None,
            }
        ]

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
    response = admin_client.post(
        "/comics/api/series", json={"provider": "comicvine", "provider_id": "49901", "monitor": "future"}
    )
    assert response.status_code == 201
    return ComicSeries.query.one()


def test_comics_need_sign_in(client, comic_dir):
    assert client.get("/comics/").status_code in (302, 401)
    assert client.get("/comics/api/import").status_code == 401


def test_every_page_renders(admin_client, saga, tmp_path, comic_dir):
    issue = saga.issues[0]
    from library.comics import files

    files.import_file(str(make_cbz(tmp_path / "Saga 001.cbz")), issue)
    for path in [
        "/comics/",
        "/comics/add?q=saga",
        f"/comics/series/{saga.id}",
        "/comics/wanted",
        "/comics/upcoming",
        "/comics/activity",
        "/comics/import",
        "/comics/settings",
        f"/comics/read/{issue.id}",
    ]:
        response = admin_client.get(path)
        assert response.status_code == 200, path
    assert b"Saga" in admin_client.get("/comics/").data


def test_empty_comics_page_says_what_to_do(standard_client, comic_dir):
    page = standard_client.get("/comics/").data.decode()
    assert "No series yet" in page and "neither is set up yet" in page
    # Standard users don't get Settings.
    assert "/comics/settings" not in page
    assert standard_client.get("/comics/settings").status_code == 302


def test_follow_series_wants_whats_coming(saga):
    assert [i.status for i in saga.issues] == [SKIPPED, SKIPPED, WANTED]


def test_lookup_marks_followed_series(admin_client, saga):
    data = admin_client.get("/comics/api/lookup?q=saga").get_json()
    assert data["results"][0]["followed_id"] == saga.id


def test_lookup_without_a_provider_explains(admin_client, comic_dir):
    response = admin_client.get("/comics/api/lookup?q=saga")
    assert response.status_code == 502 and "Settings" in response.get_json()["error"]


def test_monitor_all_and_bulk(admin_client, saga):
    admin_client.patch(f"/comics/api/series/{saga.id}", json={"monitor": "all"})
    assert all(i.status == WANTED for i in saga.issues)
    ids = [i.id for i in saga.issues]
    assert (
        admin_client.post("/comics/api/issues/bulk", json={"ids": ids, "status": "skipped"}).get_json()["changed"] == 3
    )


def test_upload_to_import_folder_matches_and_files(admin_client, saga, comic_dir):
    data = {
        "files": [
            (io.BytesIO(make_cbz(comic_dir / "tmp.cbz").read_bytes()), "Saga 002 (2024) (Digital).cbz"),
            (io.BytesIO(b"x"), "notes.txt"),
        ]
    }
    result = admin_client.post("/comics/api/import/upload", data=data, content_type="multipart/form-data").get_json()
    assert len(result["imported"]) == 1
    assert saga.issues[1].status == DOWNLOADED


def test_manual_import_into_a_new_local_series(admin_client, comic_dir):
    inbox = comic_dir / "_import"
    inbox.mkdir()
    make_cbz(inbox / "Zine 004 (2021).cbz")
    listing = admin_client.get("/comics/api/import").get_json()
    assert listing["files"][0]["reason"].startswith("No followed series")
    response = admin_client.post("/comics/api/import/file", json={"path": "Zine 004 (2021).cbz", "new_series": "Zine"})
    assert response.status_code == 200
    series = ComicSeries.query.one()
    assert series.provider == "local" and series.issues[0].number == "4" and series.issues[0].status == DOWNLOADED


def test_import_refuses_paths_outside_the_folder(admin_client, comic_dir):
    response = admin_client.post("/comics/api/import/file", json={"path": "../../etc/passwd", "new_series": "x"})
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
    shown = admin_client.get("/comics/api/settings").get_json()
    shown["max_size_mb"] = 300
    shown["rejected_words"] = "c2c, preview"
    shown["indexers"] = [
        {"name": "Geek", "url": "https://api.nzbgeek.info", "api_key": "secret-key-123", "kind": "newznab"}
    ]
    saved = admin_client.put("/comics/api/settings", json=shown).get_json()
    assert settings.get("comicvine_api_key") == "abcdef1234567890"
    assert settings.get("max_size_mb") == 300 and settings.get("rejected_words") == ["c2c", "preview"]
    # Saving again with the masked key keeps the real one.
    admin_client.put("/comics/api/settings", json=saved)
    assert settings.get("indexers")[0]["api_key"] == "secret-key-123"


def test_search_without_indexers_says_so(admin_client, saga):
    response = admin_client.post(f"/comics/api/issues/{saga.issues[1].id}/search")
    assert response.status_code == 400 and "indexer" in response.get_json()["error"]


def test_books_page_links_to_comics(admin_client):
    assert b"/comics/" in admin_client.get("/").data
