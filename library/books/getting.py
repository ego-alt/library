"""Books in the shared download pipeline (downloads/pipeline.py): which
requests are wanted, what to search for, how a release is judged, and how a
finished download's EPUB joins the library."""

import os
import re
import unicodedata

from flask import url_for

from ..downloads import pipeline
from ..downloads.models import DOWNLOADED, KIND_BOOK, WANTED, Download
from ..models import db
from .files import NotABookError, add_epub
from .models import BookRequest

# Words that don't tell titles apart.
_STOPWORDS = {"the", "a", "an", "of", "and", "&", "in", "on", "to", "for"}
_AUDIO = re.compile(r"\b(audiobook|audio ?book|mp3|m4b|aac|flac|unabridged|narrated)\b")
_OTHER_FORMATS = re.compile(r"\b(pdf|mobi|azw3?|kfx|djvu|cbz|cbr)\b")
_COLLECTION = re.compile(r"\b(collection|omnibus|box ?set|boxed set|complete works|\d+ books)\b")


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = text.replace("'", "")
    return re.findall(r"[a-z0-9]+", text)


def _title_words(title: str) -> list[str]:
    """The words that identify a title: no subtitle ("Dune: Messiah" -> dune,
    messiah stays; "Sapiens: A Brief History…" -> sapiens), no stopwords."""
    main = re.split(r"[:(\[]", title or "", maxsplit=1)[0]
    words = [w for w in _words(main) if w not in _STOPWORDS]
    return words or _words(main)


def _surname(author: str | None) -> str | None:
    """The first author's surname: "Ursula K. Le Guin" -> guin, "Terry
    Pratchett, Neil Gaiman" -> pratchett, catalogue-style "Judt, Tony" -> judt."""
    words = [w for w in _words((author or "").split(",")[0]) if w not in ("jr", "sr", "ii", "iii")]
    return words[-1] if words else None


def score_release(release, request: BookRequest, opts: dict, blocked: set[str]) -> float | None:
    """How good a release is for a book, or None when it isn't that book (or
    isn't an EPUB). Sets release.note to why, for the manual search list."""
    if release.title in blocked:
        release.note = "Failed before"
        return None
    words = set(_words(release.title))
    text = " ".join(_words(release.title))
    wanted = _title_words(request.title)
    present = [w for w in wanted if w in words]
    if len(present) < len(wanted):
        release.note = "Another title"
        return None
    surname = _surname(request.author)
    if surname and surname not in words:
        release.note = "No author name"
        return None
    if _AUDIO.search(text):
        release.note = "An audiobook"
        return None
    if _COLLECTION.search(text) and not _COLLECTION.search(" ".join(_words(request.title))):
        release.note = "A collection"
        return None
    if "epub" not in words and _OTHER_FORMATS.search(text):
        release.note = "Not an EPUB"
        return None
    title = release.title.lower()
    rejected = next((w for w in opts["rejected_words"] if w and w.lower() in title), None)
    if rejected:
        release.note = f"Has “{rejected}”"
        return None
    max_size = int(opts.get("book_max_size_mb") or 0) * 1024 * 1024
    if max_size and release.size and release.size > max_size:
        release.note = "Too big"
        return None
    if release.protocol == "torrent" and release.seeders == 0:
        release.note = "No seeders"
        return None
    # Fewer extra words means a closer match ("Dune" over "Dune Messiah").
    extra = len(words - set(wanted) - {surname} - _STOPWORDS)
    score = 1.0 - min(extra, 20) / 100
    score += 0.2 if "epub" in words else 0
    score += 0.1 if "retail" in words else 0
    score += sum(0.1 for w in opts["preferred_words"] if w and w.lower() in title)
    if release.seeders:
        score += min(release.seeders, 50) / 1000
    release.note = ""
    return score


def _best_epub(paths: list[str], request: BookRequest | None) -> str | None:
    epubs = [p for p in paths if p.lower().endswith(".epub")]
    if not epubs:
        return None
    if request is not None:
        wanted = set(_title_words(request.title))
        named = [p for p in epubs if wanted <= set(_words(os.path.basename(p)))]
        if named:
            epubs = named
    return max(epubs, key=os.path.getsize)


def import_epub(path: str, request: BookRequest | None, keep: bool = False):
    """Add an EPUB to the library, as the requested book when there is one."""
    if request is None:
        return add_epub(path, keep_source=keep)
    book = add_epub(path, title=request.title, author=request.author, uploaded_by=request.requested_by, keep_source=keep)
    request.status = DOWNLOADED
    request.book_id = book.id
    db.session.commit()
    return book


class BookKind:
    name = KIND_BOOK
    fk = "book_request_id"

    def wanted(self) -> list[BookRequest]:
        return BookRequest.query.filter_by(status=WANTED).order_by(BookRequest.created_at.desc()).all()

    def queries(self, request: BookRequest) -> list[str]:
        """Title and author, then the title alone."""
        title = " ".join(re.split(r"[:(\[]", request.title, maxsplit=1)[0].split())
        surname = _surname(request.author)
        return [f"{title} {surname}", title] if surname else [title]

    def score(self, release, request, opts, blocked):
        return score_release(release, request, opts, blocked)

    def import_files(self, download: Download, paths: list[str], keep: bool) -> None:
        path = _best_epub(paths, download.book_request)
        if path is None:
            other = next((os.path.splitext(p)[1] for p in paths if _OTHER_FORMATS.search(p.lower())), None)
            raise pipeline.ImportFilesError(f"The download has no EPUB in it{f' (only {other})' if other else ''}.")
        try:
            import_epub(path, download.book_request, keep)
        except NotABookError as e:
            raise pipeline.ImportFilesError(str(e)) from e

    def label(self, request: BookRequest) -> str:
        return request.label

    def link(self, request: BookRequest) -> str:
        if request.book is not None:
            return url_for("read_routes.read_book", filename=request.book.filename)
        return url_for("downloads.downloads_page") + "#wanted"


kind = BookKind()


def request_book(found: dict, user_id: int | None) -> tuple[BookRequest, bool]:
    """Ask for a book found on Open Library. Returns (request, new)."""
    existing = BookRequest.query.filter_by(ol_key=found.get("ol_key")).first() if found.get("ol_key") else None
    if existing is not None:
        if existing.status not in (DOWNLOADED, "snatched"):
            existing.status = WANTED
            db.session.commit()
        return existing, False
    request = BookRequest(ol_key=found.get("ol_key"), title=(found.get("title") or "").strip()[:300], author=(found.get("author") or "").strip()[:200] or None, year=found.get("year"), cover_url=found.get("cover_url"), requested_by=user_id)
    db.session.add(request)
    db.session.commit()
    return request, True
