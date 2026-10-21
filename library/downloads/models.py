"""Downloads, for books and comics alike: a release sent to a download client
for a comic issue or a book request, followed until its file is in the library.

Failed downloads stay as the blocklist: that release isn't grabbed again for
the same issue or book.
"""

from ..models import _utcnow, db

KIND_COMIC = "comic"
KIND_BOOK = "book"
KINDS = (KIND_COMIC, KIND_BOOK)

DL_QUEUED = "queued"
DL_DOWNLOADING = "downloading"
DL_IMPORTING = "importing"
DL_DONE = "done"
DL_FAILED = "failed"
DL_ACTIVE = (DL_QUEUED, DL_DOWNLOADING, DL_IMPORTING)

# What a wanted thing (a comic issue, a book request) is up to.
WANTED = "wanted"
SKIPPED = "skipped"
SNATCHED = "snatched"
DOWNLOADED = "downloaded"


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
    client = db.Column(db.String(20))  # sabnzbd | qbittorrent | blackhole
    client_ref = db.Column(db.String(200))  # the client's id for the job
    status = db.Column(db.String(12), nullable=False, default=DL_QUEUED, index=True)
    progress = db.Column(db.Float, default=0)
    error = db.Column(db.Text)
    path = db.Column(db.String(1000))  # where the client put the finished files
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    issue = db.relationship("ComicIssue", back_populates="downloads")
    book_request = db.relationship("BookRequest", back_populates="downloads")

    @property
    def item(self):
        """The issue or book request this download is for (None if it's gone)."""
        return self.book_request if self.kind == KIND_BOOK else self.issue
