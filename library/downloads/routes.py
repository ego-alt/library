"""Downloads, for admins: following everything on its way into the library,
and the APIs behind asking for books and series from the shelves' search
and adding files with the shelves' +.

  /downloads           in progress (failures that need you first) and wanted
  /settings            the tab beside it: indexers, clients, comics
  /api/get/...         searching Open Library and ComicVine/Metron
  /api/downloads/...   the queue; /api/wanted/<kind>/<id>/... searches and
                       grabs for a comic issue or a book request alike
  /api/import/stage    one comic from a shelf's +, staged to check
"""

import difflib
import io
import os
import secrets
import shutil

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from .. import settings
from ..books import getting as books
from ..books import openlibrary
from ..books.models import BookRequest
from ..choices import UserRoleChoice
from ..comics import archive, names, providers
from ..comics import downloads as comic_downloads
from ..comics import files as comic_files
from ..comics.models import ComicIssue, ComicSeries
from ..comics.series import local_series
from ..models import Book, _utcnow, db
from ..routes._helpers import json_admin_required
from ..utils import make_thumbnail
from . import clients, indexers, jobs, pipeline
from .models import (
    DL_ACTIVE,
    DL_FAILED,
    KIND_BOOK,
    KIND_COMIC,
    KINDS,
    SKIPPED,
    WANTED,
    Download,
)

downloads_blueprint = Blueprint("downloads", __name__)


def is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == UserRoleChoice.ADMIN


def waiting_count() -> int:
    """Downloads in progress (the number on the Downloads link)."""
    return pipeline.active_count()


def download_json(d: Download) -> dict:
    item = d.item
    kind = pipeline.handler(d.kind)
    return {
        "id": d.id,
        "kind": d.kind,
        "title": d.title,
        "indexer": d.indexer,
        "protocol": d.protocol,
        "client": d.client,
        "size": d.size,
        "status": d.status,
        "progress": d.progress,
        "error": clients.plain_error(d.error),
        "created_at": d.created_at.isoformat() + "Z",
        "updated_at": d.updated_at.isoformat() + "Z" if d.updated_at else None,
        "item": {"id": item.id, "label": kind.label(item), "url": kind.link(item)} if item is not None else None,
    }


def _wanted_item(kind: str, item_id: int):
    model = BookRequest if kind == KIND_BOOK else ComicIssue
    if kind not in KINDS:
        abort(404)
    item = db.session.get(model, item_id)
    if item is None:
        abort(404, description="Not found")
    return item


# Pages


@downloads_blueprint.get("/settings")
@login_required
def settings_page():
    """Settings, the tab beside Downloads."""
    if not is_admin():
        return redirect(url_for("index_routes.index"))
    return render_template("settings.html", comic_dir=comic_files.comic_dir())


@downloads_blueprint.get("/downloads")
@login_required
def downloads_page():
    if not is_admin():
        return redirect(url_for("index_routes.index"))
    from ..comics.routes import issue_json

    # Wanted: books, a line each; comics, a group per series; newest first.
    groups: dict[int, dict] = {}
    for issue in comic_downloads.wanted_issues():
        groups.setdefault(issue.series_id, {"series": issue.series, "issues": []})["issues"].append(issue_json(issue))
    try:
        every = int(float(settings.get("search_interval_hours") or 6))
    except (TypeError, ValueError):
        every = 6
    return render_template(
        "downloads.html",
        wanted_books=books.kind.wanted(),
        wanted_comics=list(groups.values()),
        can_search=bool(settings.get("indexers")),
        search_every=every,
    )


# API: Get


@downloads_blueprint.get("/api/get/search/books")
@json_admin_required
def get_search_books():
    """Books from Open Library, each marked with whether it's in the library
    (by title and author, opening it) or asked for already."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"results": [], "error": None})
    try:
        found = openlibrary.search(query)
    except openlibrary.OpenLibraryError as e:
        return jsonify({"results": [], "error": str(e)})
    requested = {r.ol_key: r for r in BookRequest.query.filter(BookRequest.ol_key.in_([b["ol_key"] for b in found]))}
    owned = {}
    for book in Book.query.filter(Book.deleted_at.is_(None)).with_entities(Book.title, Book.author, Book.filename):
        owned.setdefault((book.title or "").lower(), []).append((books.author_surname(book.author), book.filename))
    for row in found:
        request_row = requested.get(row["ol_key"])
        surname = books.author_surname(row.get("author"))
        match = next((filename for owner, filename in owned.get(row["title"].lower(), []) if not surname or not owner or owner == surname), None)
        if match is None and request_row is not None and request_row.book is not None:
            match = request_row.book.filename
        row["status"] = "have" if match else (request_row.status if request_row else None)
        row["request_id"] = request_row.id if request_row else None
        row["href"] = url_for("read_routes.read_book", filename=match) if match else None
    return jsonify({"results": found, "error": None})


@downloads_blueprint.get("/api/get/search/comics")
@json_admin_required
def get_search_comics():
    """Comic series from ComicVine or Metron, each marked with whether you
    follow it already."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"results": [], "error": None})
    if not providers.available():
        return jsonify({"results": [], "error": "Add a ComicVine key or Metron account in Settings to find comics."})
    try:
        provider = providers.get_provider()
        found = provider.search_series(query)
    except providers.ProviderError as e:
        return jsonify({"results": [], "error": str(e)})
    followed = {(s.provider, s.provider_id): s.id for s in ComicSeries.query.filter_by(provider=provider.name)}
    for row in found:
        row["followed_id"] = followed.get((row["provider"], row["provider_id"]))
    return jsonify({"results": found, "error": None})


@downloads_blueprint.post("/api/get/books")
@json_admin_required
def get_book():
    """Ask for a book found on Open Library; it's searched for straight away."""
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify({"error": "Which book?"}), 400
    book_request, created = books.request_book(data, current_user.id)
    if book_request.status == WANTED:
        # A few seconds' grace, so Undo on the toast really undoes.
        jobs.request_run("search", delay=10)
    return jsonify({"id": book_request.id, "status": book_request.status, "created": created}), 201 if created else 200


@downloads_blueprint.delete("/api/book-requests/<int:request_id>")
@json_admin_required
def delete_book_request(request_id):
    book_request = _wanted_item(KIND_BOOK, request_id)
    for download in book_request.downloads:
        if download.status in DL_ACTIVE:
            pipeline.cancel(download)
    db.session.delete(book_request)
    db.session.commit()
    return jsonify({"ok": True})


# API: searching and grabbing for anything wanted


@downloads_blueprint.post("/api/wanted/<kind>/<int:item_id>/search")
@json_admin_required
def search_wanted_item(kind, item_id):
    """Grab the best release now."""
    item = _wanted_item(kind, item_id)
    if not settings.get("indexers"):
        return jsonify({"error": "Add an indexer in Settings first."}), 400
    releases, errors = pipeline.find_releases(kind, item)
    item.searched_at = _utcnow()
    db.session.commit()
    best = next((r for r in releases if r.score >= 0), None)
    if best is None:
        if errors:
            return jsonify({"error": " ".join(errors)}), 502
        return jsonify({"found": False, "message": "Nothing yet. It'll be looked for again.", "releases": len(releases)})
    try:
        download = pipeline.grab(kind, item, best)
    except clients.ClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"download": download_json(download), "status": item.status})


@downloads_blueprint.get("/api/wanted/<kind>/<int:item_id>/releases")
@json_admin_required
def wanted_releases(kind, item_id):
    """Every release for an item, to pick one by hand. The links stay on the
    server (they can carry indexer keys); grabbing names one by its token."""
    item = _wanted_item(kind, item_id)
    if not settings.get("indexers"):
        return jsonify({"error": "Add an indexer in Settings first."}), 400
    releases, errors = pipeline.find_releases(kind, item)
    from .. import cache

    token = secrets.token_urlsafe(12)
    cache.set(f"releases:{token}", {"kind": kind, "item_id": item.id, "releases": [vars(r) for r in releases]}, timeout=1800)
    return jsonify({"token": token, "releases": [r.public() for r in releases], "errors": errors})


@downloads_blueprint.post("/api/wanted/<kind>/<int:item_id>/grab")
@json_admin_required
def grab_wanted(kind, item_id):
    item = _wanted_item(kind, item_id)
    data = request.get_json(silent=True) or {}
    from .. import cache

    saved = cache.get(f"releases:{data.get('token')}")
    if not saved or saved["kind"] != kind or saved["item_id"] != item.id:
        return jsonify({"error": "These results have expired. Search again."}), 410
    try:
        release = indexers.Release(**saved["releases"][int(data.get("index", -1))])
    except (IndexError, ValueError, TypeError):
        return jsonify({"error": "No such release."}), 400
    try:
        download = pipeline.grab(kind, item, release)
    except clients.ClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"download": download_json(download), "status": item.status})


# API: the queue and the worker


@downloads_blueprint.get("/api/downloads")
@json_admin_required
def activity():
    active = Download.query.filter(Download.status.in_(DL_ACTIVE)).order_by(Download.created_at.desc()).all()
    finished = Download.query.filter(~Download.status.in_(DL_ACTIVE)).order_by(Download.updated_at.desc()).limit(100).all()
    # Failures that still need you: the last try for something still wanted.
    latest = {}
    for d in Download.query.order_by(Download.created_at.desc()):
        latest.setdefault((d.kind, d.issue_id or d.book_request_id), d.id)
    attention = [d for d in finished if d.status == DL_FAILED and d.item is not None and d.item.status == WANTED and d.error != "Cancelled." and latest.get((d.kind, d.issue_id or d.book_request_id)) == d.id]
    worker = jobs.status()
    failed_jobs = [job for job in jobs.JOBS if worker.get(job) and not worker[job].get("ok", True)]
    return jsonify({
        "active": [download_json(d) for d in active],
        "attention": [download_json(d) for d in attention],
        "clients": list((worker.get("clients") or {}).values()),
        "paused": not worker.get("alive") or bool(failed_jobs),
    })


@downloads_blueprint.post("/api/jobs/<job>")
@json_admin_required
def run_job(job):
    if job not in jobs.JOBS:
        abort(404)
    jobs.request_run(job)
    return jsonify({"ok": True})


@downloads_blueprint.post("/api/downloads/<int:download_id>/cancel")
@json_admin_required
def cancel_download(download_id):
    download = db.session.get(Download, download_id) or abort(404)
    pipeline.cancel(download)
    return jsonify(download_json(download))


@downloads_blueprint.post("/api/downloads/<int:download_id>/retry")
@json_admin_required
def retry_download(download_id):
    """Block this release and look for another."""
    download = db.session.get(Download, download_id) or abort(404)
    if download.item is None:
        return jsonify({"error": "That isn't wanted any more."}), 404
    grabbed = pipeline.retry(download)
    if grabbed is None:
        return jsonify({"found": False, "message": "Nothing else yet. It'll be looked for again."})
    return jsonify(download_json(grabbed))


@downloads_blueprint.delete("/api/downloads/<int:download_id>")
@json_admin_required
def forget_download(download_id):
    """Dismiss a finished or failed download (a failed release can then be
    downloaded again)."""
    download = db.session.get(Download, download_id) or abort(404)
    if download.status in DL_ACTIVE:
        return jsonify({"error": "Cancel it first."}), 409
    db.session.delete(download)
    db.session.commit()
    return jsonify({"ok": True})


# API: adding one comic from a shelf's +


def _series_names() -> dict:
    return {s.id: s.display_name for s in ComicSeries.query}


def _file_row(path: str, folder: str, series_names: dict) -> dict:
    """What a comic file looks like it is: its match (if any), the closest
    followed series to start the picker on, and why it didn't match."""
    match = comic_files.match_file(path)
    guess = match.series.id if match.series else None
    if guess is None and match.parsed.series:
        close = difflib.get_close_matches(match.parsed.series.lower(), {n.lower(): i for i, n in series_names.items()}, n=1, cutoff=0.6)
        guess = next((i for i, n in series_names.items() if close and n.lower() == close[0]), None)
    return {
        "guess": guess,
        "path": os.path.relpath(path, folder),
        "size": os.path.getsize(path),
        "parsed": {"series": match.parsed.series, "number": match.parsed.number, "year": match.parsed.year},
        "issue": {"id": match.issue.id, "label": f"{match.series.display_name} #{match.issue.number}", "number": match.issue.number} if match.issue else None,
        "series": {"id": match.series.id, "name": match.series.display_name} if match.series else None,
        "reason": match.reason,
    }


def _series_options(series_names: dict) -> list:
    return [[i, n] for i, n in sorted(series_names.items(), key=lambda x: x[1].lower())]


def _issue_for(data: dict, path: str):
    """The issue a file is being filed as: one picked, or by number in a
    series picked (or a new local one named for it). Returns (issue, error)."""
    if data.get("issue_id"):
        return _wanted_item(KIND_COMIC, int(data["issue_id"])), None
    if not (data.get("series_id") or data.get("new_series")):
        return None, "Choose a series."
    number = names.normalize_number(str(data.get("number") or "")) or names.parse(os.path.basename(path)).number
    if not number:
        return None, "Which issue number is it?"
    if data.get("series_id"):
        series = db.session.get(ComicSeries, int(data["series_id"])) or abort(404)
    else:
        parsed = names.parse(os.path.basename(path))
        series = local_series((data.get("new_series") or "").strip() or parsed.series or "Unknown", parsed.year)
    issue = next((i for i in series.issues if names.normalize_number(i.number) == number), None)
    if issue is None:
        issue = ComicIssue(series=series, number=number, sort_number=names.sort_number(number), status=SKIPPED)
        db.session.add(issue)
        db.session.flush()
    return issue, None


def _file_issue(path: str, issue):
    from ..comics.routes import issue_json

    try:
        comic_files.import_file(path, issue)
    except archive.ArchiveError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    comic_downloads.mark_imported([issue.id])
    return jsonify(issue_json(issue))


# It waits, unfiled, while you check what it matched (or choose its series),
# as a book waits in its review panel.

def _staged_dir() -> str:
    return os.path.join(comic_files.comic_dir(), "_staged")


def _staged_path(name: str) -> str:
    """A staged file by its "<token>/<name>"; refuses anything else."""
    folder = os.path.realpath(_staged_dir())
    path = os.path.realpath(os.path.join(folder, name or ""))
    if not path.startswith(folder + os.sep) or os.path.dirname(path) == folder or not os.path.isfile(path):
        abort(404, description="That file has gone; choose it again.")
    return path


def _unstage(path: str) -> None:
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)


@downloads_blueprint.post("/api/import/stage")
@json_admin_required
def import_stage():
    upload = request.files.get("file")
    if upload is None or not names.is_comic_file(upload.filename or ""):
        return jsonify({"error": "Choose a CBZ, CBR or CB7 file."}), 400
    # Its own folder, so the file keeps the name matching reads.
    folder = _staged_dir()
    token_dir = os.path.join(folder, secrets.token_hex(6))
    os.makedirs(token_dir, exist_ok=True)
    path = os.path.join(token_dir, names.safe_filename(os.path.basename(upload.filename)))
    upload.save(path)
    series_names = _series_names()
    row = _file_row(path, folder, series_names)
    row["name"] = os.path.basename(upload.filename)
    return jsonify({"file": row, "series": _series_options(series_names)})


@downloads_blueprint.get("/api/import/stage/<path:name>/cover")
@json_admin_required
def import_staged_cover(name):
    """Its first page, small, for the check."""
    try:
        data = make_thumbnail(archive.first_page(_staged_path(name)), 300)
    except Exception:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="image/webp")


@downloads_blueprint.post("/api/import/stage/<path:name>")
@json_admin_required
def import_staged(name):
    path = _staged_path(name)
    issue, error = _issue_for(request.get_json(silent=True) or {}, path)
    if error:
        return jsonify({"error": error}), 400
    response = _file_issue(path, issue)
    _unstage(path)
    return response


@downloads_blueprint.delete("/api/import/stage/<path:name>")
@json_admin_required
def import_unstage(name):
    try:
        _unstage(_staged_path(name))
    except Exception:
        pass
    return jsonify({"ok": True})
