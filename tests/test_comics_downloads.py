import json
from datetime import date
from urllib.parse import parse_qs

import httpx
import pytest

from library.comics import clients, downloads, indexers, providers, settings
from library.comics.models import (
    DL_DONE,
    DL_DOWNLOADING,
    DL_FAILED,
    DOWNLOADED,
    SKIPPED,
    SNATCHED,
    WANTED,
    ComicDownload,
    ComicIssue,
    ComicSeries,
)
from library.models import db
from tests.conftest import make_cbz

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
<channel>
  <item><title>Saga 066 (2024) (Digital) (Zone-Empire)</title><link>https://idx/getnzb/a?apikey=SECRET</link><pubDate>Wed, 16 Oct 2024 10:00:00 +0000</pubDate><enclosure url="https://idx/getnzb/a.nzb?apikey=SECRET" length="51000000" type="application/x-nzb"/><newznab:attr name="size" value="52000000"/></item>
  <item><title>Saga 066 (2024) (c2c scan)</title><enclosure url="https://idx/b.nzb" length="40000000" type="application/x-nzb"/></item>
  <item><title>Saga 065 (2023) (Digital)</title><enclosure url="https://idx/c.nzb" length="40000000" type="application/x-nzb"/></item>
  <item><title>Saga Vol. 11 (2024) (TPB) (Digital)</title><enclosure url="https://idx/d.nzb" length="400000000" type="application/x-nzb"/></item>
  <item><title>Saga 066 (2024) (webrip)</title><enclosure url="https://idx/e.nzb" length="45000000" type="application/x-nzb"/></item>
  <item><title>Sagas of Old 066 (1999)</title><enclosure url="https://idx/f.nzb" length="45000000" type="application/x-nzb"/></item>
</channel></rss>"""


@pytest.fixture
def issue(app):
    s = ComicSeries(provider="comicvine", provider_id="123", name="Saga", start_year=2012, publisher="Image")
    db.session.add(s)
    i = ComicIssue(series=s, provider_id="66", number="66", sort_number=66, cover_date=date(2024, 10, 1), status=WANTED)
    db.session.add(i)
    db.session.commit()
    return i


def test_parse_feed():
    releases = indexers.parse_feed(FEED, "Geek", "usenet")
    assert len(releases) == 6
    first = releases[0]
    assert first.size == 52000000 and first.published == "2024-10-16" and first.url.endswith("apikey=SECRET")
    assert "url" not in first.public()


def test_parse_feed_error():
    with pytest.raises(indexers.IndexerError, match="Incorrect user credentials"):
        indexers.parse_feed('<error code="100" description="Incorrect user credentials"/>', "Geek", "usenet")


def test_search_asks_for_comics():
    seen = {}

    def handler(request):
        seen.update(parse_qs(request.url.query.decode()))
        return httpx.Response(200, text=FEED)

    indexers.search(
        {"name": "Geek", "url": "https://idx", "api_key": "k"}, "Saga", transport=httpx.MockTransport(handler)
    )
    assert seen["t"] == ["search"] and seen["cat"] == ["7030"] and seen["q"] == ["Saga"] and seen["apikey"] == ["k"]


def test_score_release_picks_the_right_issue(app, issue):
    opts = settings.get_all()
    releases = indexers.parse_feed(FEED, "Geek", "usenet")
    scores = {r.title: downloads.score_release(r, issue, opts, set()) for r in releases}
    assert scores["Saga 066 (2024) (Digital) (Zone-Empire)"] > scores["Saga 066 (2024) (webrip)"]
    assert scores["Saga 066 (2024) (c2c scan)"] is None
    assert scores["Saga 065 (2023) (Digital)"] is None
    assert scores["Saga Vol. 11 (2024) (TPB) (Digital)"] is None
    assert scores["Sagas of Old 066 (1999)"] is None
    blocked = {"Saga 066 (2024) (Digital) (Zone-Empire)"}
    assert downloads.score_release(releases[0], issue, opts, blocked) is None and releases[0].note == "Failed before"


class FakeClient:
    name = "sabnzbd"

    def __init__(self):
        self.added, self.states = [], {}

    def add(self, url, title, download_id, protocol="usenet"):
        self.added.append((url, title))
        return f"nzo_{download_id}"

    def state(self, ref):
        return self.states.get(ref, clients.JobState("downloading", 0.4))

    def remove(self, ref):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(clients, "client_for", lambda protocol, name=None: client)
    monkeypatch.setattr(clients, "can_download", lambda protocol: True)
    monkeypatch.setattr(
        indexers, "search", lambda indexer, query, transport=None: indexers.parse_feed(FEED, indexer["name"], "usenet")
    )
    settings.set_many(
        {"indexers": [{"name": "Geek", "kind": "newznab", "url": "https://idx", "api_key": "k", "enabled": True}]}
    )
    return client


def test_search_grab_download_import(app, comic_dir, tmp_path, issue, fake_client):
    assert downloads.search_wanted() == 1
    assert fake_client.added[0][1] == "Saga 066 (2024) (Digital) (Zone-Empire)"
    download = ComicDownload.query.one()
    assert download.status == DL_DOWNLOADING and issue.status == SNATCHED

    assert downloads.check_downloads() == 1
    assert download.progress == 0.4

    done = tmp_path / "complete" / "Saga 066 (2024) (Digital) (Zone-Empire)"
    done.mkdir(parents=True)
    make_cbz(done / "Saga 066 (2024) (Digital) (Zone-Empire).cbz")
    fake_client.states[download.client_ref] = clients.JobState("done", 1.0, str(done))
    assert downloads.check_downloads() == 0
    assert download.status == DL_DONE
    assert issue.status == DOWNLOADED and issue.filename.endswith("Saga #066 (2024).cbz")
    assert not done.exists()


def test_failed_download_blocks_that_release(app, comic_dir, issue, fake_client):
    downloads.search_wanted()
    download = ComicDownload.query.one()
    fake_client.states[download.client_ref] = clients.JobState("failed", error="Out of retention")
    downloads.check_downloads()
    assert download.status == DL_FAILED and download.error == "Out of retention"
    assert issue.status == WANTED
    # The next search takes the next best release.
    downloads.search_wanted()
    assert fake_client.added[-1][1] == "Saga 066 (2024) (webrip)"


def test_done_but_invisible_path_fails_with_a_hint(app, comic_dir, issue, fake_client):
    downloads.search_wanted()
    download = ComicDownload.query.one()
    fake_client.states[download.client_ref] = clients.JobState("done", 1.0, "/nowhere/Saga")
    downloads.check_downloads()
    assert download.status == DL_FAILED and "path mapping" in download.error


def test_unreleased_issues_are_not_searched(app, issue, fake_client):
    issue.cover_date = date(2999, 1, 1)
    db.session.commit()
    assert downloads.search_wanted() == 0


def test_sabnzbd_client(app):
    calls = []

    def handler(request):
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        calls.append(q)
        if q["mode"] == "addurl":
            return httpx.Response(200, json={"status": True, "nzo_ids": ["SABnzbd_nzo_1"]})
        if q["mode"] == "queue":
            return httpx.Response(200, json={"queue": {"slots": []}})
        return httpx.Response(
            200,
            json={
                "history": {
                    "slots": [
                        {"nzo_id": "SABnzbd_nzo_1", "status": "Completed", "storage": "/downloads/complete/Saga 066"}
                    ]
                }
            },
        )

    sab = clients.SABnzbd(
        {"url": "http://sab:8080", "api_key": "k", "category": "comics"}, transport=httpx.MockTransport(handler)
    )
    assert sab.add("https://idx/a.nzb", "Saga 066", 7) == "SABnzbd_nzo_1"
    assert calls[0]["cat"] == "comics" and calls[0]["nzbname"] == "Saga 066 [shelves-7]"
    state = sab.state("SABnzbd_nzo_1")
    assert state.state == "done" and state.path == "/downloads/complete/Saga 066"


def test_path_mapping(app):
    settings.set_many({"path_map": {"remote_path": "/downloads", "local_path": "/data/downloads"}})
    assert clients.map_path("/downloads/complete/x") == "/data/downloads/complete/x"
    assert clients.map_path("/downloadsother/x") == "/downloadsother/x"


def test_qbittorrent_client(app):
    def handler(request):
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=abc"})
        if path.endswith("/torrents/add"):
            assert b"tags=shelves-3" in request.content
            return httpx.Response(200, text="Ok.")
        if path.endswith("/torrents/info"):
            return httpx.Response(
                200,
                json=[
                    {
                        "hash": "h",
                        "name": "Saga 066",
                        "progress": 1,
                        "state": "stalledUP",
                        "content_path": "/downloads/Saga 066.cbz",
                    }
                ],
            )
        return httpx.Response(404)

    qb = clients.QBittorrent(
        {"url": "http://qb:8081", "username": "u", "password": "p"}, transport=httpx.MockTransport(handler)
    )
    assert qb.add("magnet:?xt=1", "Saga 066", 3) == "shelves-3"
    state = qb.state("shelves-3")
    assert state.state == "done" and state.path == "/downloads/Saga 066.cbz"


def test_comicvine_provider():
    def handler(request):
        assert request.url.params["api_key"] == "key"
        if "/search/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "status_code": 1,
                    "results": [
                        {
                            "id": 49901,
                            "name": "Saga",
                            "start_year": "2012",
                            "publisher": {"name": "Image"},
                            "count_of_issues": 66,
                            "image": {"medium_url": "https://cv/saga.jpg"},
                            "deck": "Space opera",
                        }
                    ],
                },
            )
        if "/issues/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "status_code": 1,
                    "number_of_total_results": 1,
                    "results": [
                        {
                            "id": 1,
                            "issue_number": "1",
                            "name": "Chapter One",
                            "cover_date": "2012-03-01",
                            "store_date": "2012-03-14",
                            "image": {"medium_url": "https://cv/1.jpg"},
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"status_code": 100, "error": "Invalid API Key"})

    cv = providers.ComicVine("key", transport=httpx.MockTransport(handler))
    cv.throttle.interval = 0
    [series] = cv.search_series("saga")
    assert series["provider_id"] == "49901" and series["start_year"] == 2012 and series["publisher"] == "Image"
    [issue] = cv.get_issues("49901")
    assert issue["number"] == "1" and issue["store_date"] == date(2012, 3, 14)
    with pytest.raises(providers.ProviderError, match="Invalid API Key"):
        cv.get_series("49901")


def test_metron_provider_follows_pages():
    def handler(request):
        if request.url.path.endswith("/issue/") and "page" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "next": "https://metron.cloud/api/issue/?series_id=5&page=2",
                    "results": [{"id": 1, "number": "1", "cover_date": "2020-01-01", "image": "https://m/1.jpg"}],
                },
            )
        if request.url.path.endswith("/issue/"):
            return httpx.Response(
                200, json={"next": None, "results": [{"id": 2, "number": "2", "store_date": "2020-02-05"}]}
            )
        return httpx.Response(401)

    metron = providers.Metron("u", "p", transport=httpx.MockTransport(handler))
    metron.throttle.interval = 0
    assert [i["number"] for i in metron.get_issues("5")] == ["1", "2"]
    with pytest.raises(providers.ProviderError, match="refused"):
        metron.get_series("5")


def test_settings_mask_secrets(app):
    settings.set_many(
        {"comicvine_api_key": "abcdef1234567890", "indexers": [{"name": "Geek", "api_key": "zzzzzzzz9999"}]}
    )
    shown = settings.for_browser()
    assert shown["comicvine_api_key"] == "••••••••7890"
    assert shown["indexers"][0]["api_key"].endswith("9999") and "zzzz" not in json.dumps(shown)
    assert settings.get("comicvine_api_key") == "abcdef1234567890"


def test_skipped_issue_is_not_searched(app, issue, fake_client):
    issue.status = SKIPPED
    db.session.commit()
    assert downloads.search_wanted() == 0
