"""Downloads, for books and comics alike: a release sent to a download client
for a comic issue or a book request, followed until its file is in the library.

Failed and cancelled downloads stay as the blocklist: that release isn't
grabbed again for the same issue or book.

A download's status is only changed in downloads/pipeline.py, and a wanted
thing's only through the functions below (tests/test_states.py checks both).
"""

from ..models import UtcDateTime, _utcnow, db

KIND_COMIC = "comic"
KIND_BOOK = "book"
KINDS = (KIND_COMIC, KIND_BOOK)

DL_QUEUED = "queued"
DL_DOWNLOADING = "downloading"
DL_IMPORTING = "importing"
DL_DONE = "done"
DL_FAILED = "failed"
DL_CANCELLED = "cancelled"
DL_ACTIVE = (DL_QUEUED, DL_DOWNLOADING, DL_IMPORTING)
DL_BLOCKED = (DL_FAILED, DL_CANCELLED)

# What a wanted thing (a comic issue, a book request) is up to.
WANTED = "wanted"
SKIPPED = "skipped"
SNATCHED = "snatched"
DOWNLOADED = "downloaded"


def set_wanted(item, status: str) -> bool:
    """Want or skip an issue or book. One that's downloading or already here
    keeps its status: returns False."""
    if status not in (WANTED, SKIPPED):
        raise ValueError(status)
    if item.status in (SNATCHED, DOWNLOADED):
        return False
    item.status = status
    return True


def snatched(item) -> None:
    """A release for it went to a download client."""
    item.status = SNATCHED


def unsnatched(item) -> None:
    """Its download failed or was cancelled: it's wanted again."""
    if item.status == SNATCHED:
        item.status = WANTED


def downloaded(item) -> None:
    """Its file is in the library."""
    item.status = DOWNLOADED


def file_removed(item) -> None:
    """Its file was deleted; it isn't wanted again until you say so."""
    item.status = SKIPPED


class Download(db.Model):
    __tablename__ = "downloads"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False, default=KIND_COMIC)
    # What it's for: one of these, by kind.
    issue_id = db.Column(db.Integer, db.ForeignKey("comic_issues.id", ondelete="SET NULL"), index=True)
    book_request_id = db.Column(db.Integer, db.ForeignKey("book_requests.id", ondelete="SET NULL"), index=True)
    title = db.Column(db.String(500), nullable=False)  # the release's name
    indexer = db.Column(db.String(100))
    protocol = db.Column(db.String(10))  # usenet | torrent
    # The NZB/torrent link. It can carry the indexer's API key, so it is
    # never sent to the browser.
    url = db.Column(db.Text)
    size = db.Column(db.BigInteger)
    client = db.Column(db.String(20))  # sabnzbd | qbittorrent
    client_ref = db.Column(db.String(200))  # the client's id for the job
    status = db.Column(db.String(12), nullable=False, default=DL_QUEUED, index=True)
    progress = db.Column(db.Float, default=0)
    error = db.Column(db.Text)
    path = db.Column(db.String(1000))  # where the client put the finished files
    created_at = db.Column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    issue = db.relationship("ComicIssue", back_populates="downloads")
    book_request = db.relationship("BookRequest", back_populates="downloads")

    @property
    def item(self):
        """The issue or book request this download is for (None if it's gone)."""
        return self.book_request if self.kind == KIND_BOOK else self.issue
