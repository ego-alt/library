"""Get and Downloads, for admins: one place to ask for books and comics, and
one place to follow everything on its way into the library.

  /get                 search Open Library and ComicVine/Metron together
  /downloads           in progress, wanted, import, coming up, history, jobs
  /api/downloads/...   the queue; /api/wanted/<kind>/<id>/... searches and
                       grabs for a comic issue or a book request alike
"""

import os
import secrets
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
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
from ..models import Book, db
from ..routes._helpers import json_admin_required
from . import clients, indexers, jobs, pipeline
from .models import DL_ACTIVE, KIND_BOOK, KIND_COMIC, KINDS, SKIPPED, WANTED, Download

downloads_blueprint = Blueprint("downloads", __name__)


def is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == UserRoleChoice.ADMIN


def waiting_count() -> int:
    """What's moving or needs a hand: downloads in progress and files waiting
    in the import folder (shown on the Downloads link)."""
    folder = comic_files.import_dir()
    waiting = len(comic_files.comic_files(folder)) if os.path.isdir(folder) else 0
    return pipeline.active_count() + waiting


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
        "error": d.error,
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


@downloads_blueprint.get("/get")
@login_required
def get_page():
    if not is_admin():
        return redirect(url_for("index_routes.index"))
    return render_template("get.html", query=request.args.get("q", ""), providers_ready=bool(providers.available()))


@downloads_blueprint.get("/downloads")
@login_required
def downloads_page():
    if not is_admin():
        return redirect(url_for("index_routes.index"))
    from ..comics.routes import issue_json

    today = date.today()
    soon = ComicIssue.query.filter(ComicIssue.filename.is_(None), db.or_(ComicIssue.store_date > today, db.and_(ComicIssue.store_date.is_(None), ComicIssue.cover_date > today))).all()
    soon = [i for i in soon if i.release_date and i.release_date <= today + timedelta(days=60) and i.series.monitor != "none"]
    soon.sort(key=lambda i: (i.release_date, i.series.name, i.sort_number))
    # Wanted: a group per comic series, a line per book, newest first.
    groups: dict[int, dict] = {}
    for issue in comic_downloads.wanted_issues():
        group = groups.setdefault(issue.series_id, {"kind": KIND_COMIC, "series": issue.series, "issues": [], "date": issue.release_date})
        group["issues"].append(issue_json(issue))
    wanted = list(groups.values())
    wanted += [{"kind": KIND_BOOK, "request": r, "date": r.created_at.date()} for r in books.kind.wanted()]
    wanted.sort(key=lambda g: g["date"] or date.min, reverse=True)
    snatched = BookRequest.query.filter_by(status="snatched").count()
    return render_template(
        "downloads.html",
        wanted=wanted,
        wanted_count=sum(len(g["issues"]) if g["kind"] == KIND_COMIC else 1 for g in wanted),
        books_on_the_way=snatched,
        upcoming=[issue_json(i) for i in soon],
        series_options=[[s.id, s.display_name] for s in ComicSeries.query.order_by(ComicSeries.name)],
        can_search=bool(settings.get("indexers")),
    )


# API: Get


@downloads_blueprint.get("/api/get/search")
@json_admin_required
def get_search():
    """Books from Open Library and comic series from ComicVine/Metron, each
    marked with whether you have or follow it already."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"books": [], "comics": [], "errors": {}})
    errors, found_books, found_comics = {}, [], []
    try:
        found_books = openlibrary.search(query)
    except openlibrary.OpenLibraryError as e:
        errors["books"] = str(e)
    requested = {r.ol_key: r for r in BookRequest.query.filter(BookRequest.ol_key.in_([b["ol_key"] for b in found_books]))}
    titles = {(b.title or "").lower() for b in Book.query.filter(Book.deleted_at.is_(None)).with_entities(Book.title)}
    for book in found_books:
        request_row = requested.get(book["ol_key"])
        book["status"] = "have" if book["title"].lower() in titles or (request_row and request_row.status == "downloaded") else (request_row.status if request_row else None)
    if providers.available():
        try:
            provider = providers.get_provider()
            found_comics = provider.search_series(query)
            followed = {(s.provider, s.provider_id): s.id for s in ComicSeries.query.filter_by(provider=provider.name)}
            for row in found_comics:
                row["followed_id"] = followed.get((row["provider"], row["provider_id"]))
        except providers.ProviderError as e:
            errors["comics"] = str(e)
    else:
        errors["comics"] = "Add a ComicVine key or Metron account in Settings to find comics."
    return jsonify({"books": found_books, "comics": found_comics, "errors": errors})


@downloads_blueprint.post("/api/get/books")
@json_admin_required
def get_book():
    """Ask for a book found on Open Library; it's searched for straight away."""
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify({"error": "Which book?"}), 400
    book_request, created = books.request_book(data, current_user.id)
    if book_request.status == WANTED:
        jobs.request_run("search")
    return jsonify({"id": book_request.id, "status": book_request.status, "created": created}), 201 if created else 200


@downloads_blueprint.patch("/api/book-requests/<int:request_id>")
@json_admin_required
def update_book_request(request_id):
    book_request = _wanted_item(KIND_BOOK, request_id)
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in (WANTED, SKIPPED):
        return jsonify({"error": "A request can be wanted or skipped."}), 400
    book_request.status = status
    db.session.commit()
    return jsonify({"id": book_request.id, "status": book_request.status})


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
    best = next((r for r in releases if r.score >= 0), None)
    if best is None:
        return jsonify({"error": "; ".join(errors) or "Nothing on the indexers fits yet.", "releases": len(releases)}), 404
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
        return jsonify({"error": "That list is out of date; search again."}), 410
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
    history = Download.query.filter(~Download.status.in_(DL_ACTIVE)).order_by(Download.updated_at.desc()).limit(100).all()
    return jsonify({"active": [download_json(d) for d in active], "history": [download_json(d) for d in history], "worker": jobs.status()})


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
        return jsonify({"error": "What it was for is gone."}), 404
    grabbed = pipeline.retry(download)
    if grabbed is None:
        return jsonify({"error": "Nothing else fits yet; it stays wanted."}), 404
    return jsonify(download_json(grabbed))


@downloads_blueprint.delete("/api/downloads/<int:download_id>")
@json_admin_required
def forget_download(download_id):
    """Remove a finished or failed download from the history (and the blocklist)."""
    download = db.session.get(Download, download_id) or abort(404)
    if download.status in DL_ACTIVE:
        return jsonify({"error": "Cancel it first."}), 409
    db.session.delete(download)
    db.session.commit()
    return jsonify({"ok": True})


# API: the import folder


@downloads_blueprint.get("/api/import")
@json_admin_required
def import_list():
    """Comics in the import folder that didn't match an issue on their own."""
    folder = comic_files.import_dir()
    os.makedirs(folder, exist_ok=True)
    rows = []
    for path in comic_files.comic_files(folder):
        match = comic_files.match_file(path)
        rows.append({
            "path": os.path.relpath(path, folder),
            "size": os.path.getsize(path),
            "parsed": {"series": match.parsed.series, "number": match.parsed.number, "year": match.parsed.year},
            "issue": {"id": match.issue.id, "label": f"{match.series.display_name} #{match.issue.number}"} if match.issue else None,
            "series": {"id": match.series.id, "name": match.series.display_name} if match.series else None,
            "reason": match.reason,
        })
    return jsonify({"files": rows, "folder": folder})


@downloads_blueprint.post("/api/import/upload")
@json_admin_required
def import_upload():
    """Comics and EPUBs from your computer into the import folder, then
    imported: comics matched to their issues, EPUBs added to the books."""
    folder = comic_files.import_dir()
    os.makedirs(folder, exist_ok=True)
    saved = 0
    for upload in request.files.getlist("files"):
        filename = upload.filename or ""
        if not (names.is_comic_file(filename) or filename.lower().endswith(".epub")):
            continue
        # Keep the name as it was (it's what matching reads), just safely.
        upload.save(os.path.join(folder, names.safe_filename(os.path.basename(filename))))
        saved += 1
    if not saved:
        return jsonify({"error": "Choose CBZ, CBR, CB7 or EPUB files."}), 400
    return jsonify({"saved": saved, **jobs.import_all()})


@downloads_blueprint.post("/api/import/scan")
@json_admin_required
def import_scan():
    return jsonify(jobs.import_all())


@downloads_blueprint.post("/api/import/file")
@json_admin_required
def import_one():
    """Import one comic as an issue you pick, or as a new local series when
    no provider knows it."""
    from ..comics.routes import issue_json

    data = request.get_json(silent=True) or {}
    try:
        path = comic_files.import_folder_path(data.get("path", ""))
    except FileNotFoundError:
        return jsonify({"error": "That file isn't in the import folder any more."}), 404
    if data.get("issue_id"):
        issue = _wanted_item(KIND_COMIC, int(data["issue_id"]))
    elif data.get("series_id") or data.get("new_series"):
        number = names.normalize_number(str(data.get("number") or "")) or names.parse(os.path.basename(path)).number
        if not number:
            return jsonify({"error": "Which issue number is it?"}), 400
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
    else:
        return jsonify({"error": "Pick an issue or a series."}), 400
    try:
        comic_files.import_file(path, issue)
    except archive.ArchiveError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    comic_downloads.mark_imported([issue.id])
    return jsonify(issue_json(issue))


@downloads_blueprint.delete("/api/import/file")
@json_admin_required
def import_delete():
    try:
        path = comic_files.import_folder_path(request.args.get("path", ""))
    except FileNotFoundError:
        return jsonify({"ok": True})
    os.remove(path)
    return jsonify({"ok": True})

