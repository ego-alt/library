
import pytest

from library import settings
from library.books import getting, openlibrary
from library.books.models import BookRequest
from library.downloads import clients, indexers, pipeline
from library.downloads.models import (
    DL_DONE,
    DL_DOWNLOADING,
    DOWNLOADED,
    SNATCHED,
    WANTED,
    Download,
)
from library.models import Book
from tests._epub_builder import build_epub3

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
<channel>
  <item><title>Ursula K Le Guin - The Left Hand of Darkness (1969) (retail) (epub)</title><enclosure url="https://idx/get/1" length="900000"/></item>
  <item><title>Ursula K Le Guin - The Left Hand of Darkness (audiobook) mp3</title><enclosure url="https://idx/get/2" length="300000000"/></item>
  <item><title>Le Guin - The Left Hand of Darkness [pdf]</title><enclosure url="https://idx/get/3" length="5000000"/></item>
  <item><title>Ursula Le Guin - Hainish Collection 8 books epub</title><enclosure url="https://idx/get/4" length="9000000"/></item>
  <item><title>Someone Else - The Left Hand of Darkness epub</title><enclosure url="https://idx/get/5" length="900000"/></item>
</channel>
</rss>"""


@pytest.fixture
def wanted(app):
    request, _ = getting.request_book({"ol_key": "/works/OL59863W", "title": "The Left Hand of Darkness", "author": "Ursula K. Le Guin", "year": 1969}, None)
    return request


def test_score_picks_the_epub_and_says_why_not_the_rest(app, wanted):
    opts = settings.get_all()
    releases = indexers.parse_feed(FEED, "Geek", "usenet")
    notes = {}
    for release in releases:
        score = getting.score_release(release, wanted, opts, set())
        notes[release.title] = (score, release.note)
    best = max((r for r in releases if notes[r.title][0] is not None), key=lambda r: notes[r.title][0])
    assert best.title.endswith("(retail) (epub)")
    assert [n for _, n in notes.values()][1:] == ["An audiobook", "Not an EPUB", "Another title", "No author name"]


def test_surname():
    assert getting._surname("Ursula K. Le Guin") == "guin"
    assert getting._surname("Terry Pratchett, Neil Gaiman") == "pratchett"
    assert getting._surname("Judt, Tony") == "judt"
    assert getting._surname("Martin Luther King Jr.") == "king"


class FakeClient:
    name = "sabnzbd"

    def __init__(self):
        self.added, self.states = [], {}

    def add(self, url, title, download_id, protocol="usenet", kind="comic"):
        self.added.append((title, kind))
        return f"nzo_{download_id}"

    def state(self, ref):
        return self.states.get(ref, clients.JobState("downloading", 0.2))

    def remove(self, ref):
        pass


def test_request_search_download_and_import(app, wanted, tmp_path, monkeypatch, book_dir):
    client = FakeClient()
    monkeypatch.setattr(clients, "client_for", lambda protocol, name=None: client)
    monkeypatch.setattr(clients, "can_download", lambda protocol: True)
    asked = []
    monkeypatch.setattr(indexers, "search", lambda indexer, query, kind="comic", transport=None: asked.append((query, kind)) or indexers.parse_feed(FEED, indexer["name"], "usenet"))
    settings.set_many({"indexers": [{"name": "Geek", "kind": "newznab", "url": "https://idx", "api_key": "k", "enabled": True}]})

    assert pipeline.search_wanted() == 1
    assert asked[0] == ("The Left Hand of Darkness guin", "book")
    download = Download.query.one()
    assert download.kind == "book" and download.status == DL_DOWNLOADING and wanted.status == SNATCHED
    assert client.added[0][1] == "book"

    done = tmp_path / "complete" / "Left Hand"
    done.mkdir(parents=True)
    (done / "The Left Hand of Darkness - Ursula K. Le Guin.epub").write_bytes(build_epub3(title="The Left Hand of Darkness", author="Ursula K. Le Guin"))
    (done / "cover.jpg").write_bytes(b"x")
    client.states[download.client_ref] = clients.JobState("done", 1.0, str(done))
    assert pipeline.check_downloads() == 0
    assert download.status == DL_DONE and wanted.status == DOWNLOADED
    book = Book.query.one()
    assert wanted.book_id == book.id and book.title == "The Left Hand of Darkness" and (book_dir / book.filename).exists()


def test_import_folder_epub_fulfils_a_request(app, wanted, comic_dir, book_dir):
    inbox = comic_dir / "_import"
    inbox.mkdir()
    (inbox / "the_left_hand_of_darkness.epub").write_bytes(build_epub3(title="tlhod", author="x"))
    (inbox / "Something else.epub").write_bytes(build_epub3(title="Another Book", author="Somebody"))
    result = getting.scan_import_dir(str(inbox))
    assert len(result["imported"]) == 2 and wanted.status == DOWNLOADED
    assert {b.title for b in Book.query} == {"The Left Hand of Darkness", "Another Book"}
    assert not list(inbox.iterdir())


def test_get_api_requests_a_book_once(admin_client, comic_dir):
    found = {"ol_key": "/works/OL1W", "title": "Piranesi", "author": "Susanna Clarke", "year": 2020}
    first = admin_client.post("/api/get/books", json=found)
    assert first.status_code == 201 and first.get_json()["status"] == WANTED
    again = admin_client.post("/api/get/books", json=found)
    assert again.status_code == 200 and BookRequest.query.count() == 1
    page = admin_client.get("/downloads").data.decode()
    assert "Piranesi" in page and 'data-kind="book"' in page
    request_id = first.get_json()["id"]
    assert admin_client.delete(f"/api/book-requests/{request_id}").status_code == 200
    assert BookRequest.query.count() == 0


def test_epub_in_the_import_folder_joins_the_library(admin_client, comic_dir, book_dir):
    inbox = comic_dir / "_import"
    inbox.mkdir()
    (inbox / "dropped.epub").write_bytes(build_epub3(title="Dropped In", author="A Writer"))
    result = admin_client.post("/api/import/scan").get_json()
    assert len(result["imported"]) == 1 and Book.query.one().title == "Dropped In"


def test_openlibrary_search_parses_docs():
    import httpx

    def handler(request):
        assert request.url.params["q"] == "piranesi"
        return httpx.Response(200, json={"docs": [{"key": "/works/OL1W", "title": "Piranesi", "author_name": ["Susanna Clarke"], "first_publish_year": 2020, "cover_i": 123}, {"title": "no key"}]})

    results = openlibrary.search("piranesi", transport=httpx.MockTransport(handler))
    assert results == [{"ol_key": "/works/OL1W", "title": "Piranesi", "author": "Susanna Clarke", "year": 2020, "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg"}]
