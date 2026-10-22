"""Books you've asked for: found on Open Library, searched for on the
indexers, and added to the library when their EPUB arrives."""

from ..downloads.models import WANTED
from ..models import _utcnow, db


class BookRequest(db.Model):
    __tablename__ = "book_requests"

    id = db.Column(db.Integer, primary_key=True)
    # Open Library's work key ("/works/OL45883W"); none for one typed by hand.
    ol_key = db.Column(db.String(40), unique=True)
    title = db.Column(db.String(300), nullable=False)
    author = db.Column(db.String(200))
    year = db.Column(db.Integer)
    cover_url = db.Column(db.String(500))
    status = db.Column(db.String(12), nullable=False, default=WANTED, index=True)
    # The book it became, once imported.
    book_id = db.Column(db.Integer, db.ForeignKey("books.id", ondelete="SET NULL"))
    # Who asked: admins for now; later anyone, with an admin approving.
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    # When the indexers were last asked for it.
    searched_at = db.Column(db.DateTime)

    book = db.relationship("Book")
    downloads = db.relationship("Download", back_populates="book_request", passive_deletes=True)

    @property
    def label(self) -> str:
        return f"{self.title} by {self.author}" if self.author else self.title
