"""Comics: series you follow, their issues, the files you have, and downloads.

A series comes from one metadata provider (ComicVine or Metron), or is "local"
when it was made from files with no provider match. Issue status is what
Mylar calls it: wanted issues get searched for, snatched ones are downloading,
downloaded ones have a file in COMIC_DIR. Downloads themselves are shared with
books (downloads/models.py).
"""

from datetime import date

from ..downloads.models import SKIPPED
from ..models import _utcnow, db

# Which issues of a series are wanted: every missing one, only those released
# from now on, or none (you mark them yourself).
MONITOR_ALL = "all"
MONITOR_FUTURE = "future"
MONITOR_NONE = "none"
MONITOR_CHOICES = (MONITOR_ALL, MONITOR_FUTURE, MONITOR_NONE)

class ComicSeries(db.Model):
    __tablename__ = "comic_series"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(16), nullable=False)  # comicvine | metron | local
    provider_id = db.Column(db.String(32), nullable=False)
    # Cross-references, when the provider gives them (Metron knows ComicVine ids).
    cv_id = db.Column(db.Integer)
    metron_id = db.Column(db.Integer)
    name = db.Column(db.String(200), nullable=False)
    start_year = db.Column(db.Integer)
    publisher = db.Column(db.String(120))
    volume = db.Column(db.Integer)
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(500))
    issue_count = db.Column(db.Integer)
    monitor = db.Column(db.String(10), nullable=False, default=MONITOR_FUTURE)
    # Folder under COMIC_DIR holding this series' files.
    folder = db.Column(db.String(400))
    added_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    refreshed_at = db.Column(db.DateTime)

    issues = db.relationship("ComicIssue", back_populates="series", cascade="all, delete-orphan", order_by="ComicIssue.sort_number")

    __table_args__ = (db.UniqueConstraint("provider", "provider_id", name="uq_comic_series_provider"),)

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.start_year})" if self.start_year else self.name


class ComicIssue(db.Model):
    __tablename__ = "comic_issues"

    id = db.Column(db.Integer, primary_key=True)
    series_id = db.Column(db.Integer, db.ForeignKey("comic_series.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = db.Column(db.String(32))
    number = db.Column(db.String(20), nullable=False)
    # "1", "1.5", "½", "1.MU" sort as numbers where they can.
    sort_number = db.Column(db.Float, nullable=False, default=0)
    title = db.Column(db.String(300))
    cover_date = db.Column(db.Date)
    store_date = db.Column(db.Date)
    cover_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    status = db.Column(db.String(12), nullable=False, default=SKIPPED, index=True)
    # The file, relative to COMIC_DIR, once we have it.
    filename = db.Column(db.String(500), unique=True)
    file_size = db.Column(db.Integer)
    page_count = db.Column(db.Integer)
    original_filename = db.Column(db.String(500))
    added_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    series = db.relationship("ComicSeries", back_populates="issues")
    downloads = db.relationship("Download", back_populates="issue", passive_deletes=True)

    __table_args__ = (db.UniqueConstraint("series_id", "provider_id", name="uq_comic_issue_provider"),)

    @property
    def release_date(self) -> date | None:
        return self.store_date or self.cover_date

    @property
    def released(self) -> bool:
        released = self.release_date
        return released is None or released <= date.today()


class ComicProgress(db.Model):
    __tablename__ = "comic_progress"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    issue_id = db.Column(db.Integer, db.ForeignKey("comic_issues.id", ondelete="CASCADE"), nullable=False)
    page = db.Column(db.Integer, nullable=False, default=0)
    finished = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "issue_id", name="uq_comic_progress_user_issue"),)
