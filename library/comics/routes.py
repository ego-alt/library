"""Comics pages and their JSON API, under /comics/.

Anyone signed in can read the comics there are files for. Following series,
downloading, importing and settings are for admins.
"""

import os
import secrets
from datetime import date, timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..models import db
from ..routes._helpers import json_admin_required, json_login_required
from ..utils import make_thumbnail
from . import (
    archive,
    clients,
    downloads,
    files,
    indexers,
    jobs,
    names,
    providers,
    settings,
)
from .models import (
    DL_ACTIVE,
    DL_FAILED,
    DOWNLOADED,
    MONITOR_CHOICES,
    SKIPPED,
    SNATCHED,
    WANTED,
    ComicDownload,
    ComicIssue,
    ComicProgress,
    ComicSeries,
)
from .series import add_series, local_series, refresh_series, set_monitor

comics_blueprint = Blueprint("comics", __name__, url_prefix="/comics", template_folder="../templates")


def _series_or_404(series_id: int) -> ComicSeries:
    series = db.session.get(ComicSeries, series_id)
    if series is None:
        abort(404, description="Series not found")
    return series


def _issue_or_404(issue_id: int) -> ComicIssue:
    issue = db.session.get(ComicIssue, issue_id)
    if issue is None:
        abort(404, description="Issue not found")
    return issue


def _is_admin() -> bool:
    return current_user.is_authenticated and current_user.role.value == "admin"


def _cover(issue: ComicIssue, width: int = 300) -> str | None:
    if issue.filename:
        return url_for("comics.issue_cover", issue_id=issue.id, w=width, v=issue.file_size or 0)
    return issue.cover_url


def _series_cover(series: ComicSeries) -> str | None:
    have = next((i for i in series.issues if i.filename), None)
    if series.cover_url:
        return series.cover_url
    return _cover(have) if have else None


def _progress_by_issue(issue_ids) -> dict:
    if not current_user.is_authenticated or not issue_ids:
        return {}
    rows = ComicProgress.query.filter(ComicProgress.user_id == current_user.id, ComicProgress.issue_id.in_(list(issue_ids))).all()
    return {p.issue_id: p for p in rows}


def issue_json(issue: ComicIssue, progress: ComicProgress | None = None) -> dict:
    return {
        "id": issue.id,
        "series_id": issue.series_id,
        "series": issue.series.display_name,
        "number": issue.number,
        "title": issue.title,
        "date": issue.release_date.isoformat() if issue.release_date else None,
        "released": issue.released,
        "status": issue.status,
        "cover": _cover(issue),
        "has_file": bool(issue.filename),
        "pages": issue.page_count,
        "size": issue.file_size,
        "original_filename": issue.original_filename,
        "page": progress.page if progress else 0,
        "finished": bool(progress and progress.finished),
    }


def download_json(d: ComicDownload) -> dict:
    return {
        "id": d.id,
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
        "issue": {"id": d.issue.id, "series_id": d.issue.series_id, "label": f"{d.issue.series.display_name} #{d.issue.number}"} if d.issue else None,
    }


def _downloads_count() -> int:
    """What's moving or needs a hand: downloads in progress and files waiting
    in the import folder."""
    active = ComicDownload.query.filter(ComicDownload.status.in_(DL_ACTIVE)).count()
    waiting = len(files.comic_files(files.import_dir())) if os.path.isdir(files.import_dir()) else 0
    return active + waiting


def _page(template: str, active: str, **context):
    admin = _is_admin()
    return render_template(f"comics/{template}", active=active, downloads_count=_downloads_count() if admin else 0, is_admin=admin, providers_ready=bool(providers.available()), **context)


def _admin_page():
    """Send anyone but an admin back to the library."""
    return None if _is_admin() else redirect(url_for("comics.index"))


# Pages


@comics_blueprint.get("/")
@login_required
def index():
    admin = _is_admin()
    series = ComicSeries.query.order_by(ComicSeries.name).all()
    cards = []
    for s in series:
        have = sum(1 for i in s.issues if i.filename)
        if not have and not admin:
            continue
        upcoming = sum(1 for i in s.issues if not i.released)
        cards.append({"series": s, "cover": _series_cover(s), "have": have, "total": len(s.issues), "upcoming": upcoming, "added": s.added_at})
    return _page("index.html", "series", cards=cards, reading=_continue_reading())


def _continue_reading(limit: int = 8) -> list[dict]:
    """Issues you're partway through, most recent first."""
    rows = ComicProgress.query.filter_by(user_id=current_user.id, finished=False).filter(ComicProgress.page > 0).order_by(ComicProgress.updated_at.desc()).limit(limit * 2).all()
    reading = []
    for p in rows:
        issue = db.session.get(ComicIssue, p.issue_id)
        if issue and issue.filename:
            reading.append({"issue": issue, "cover": _cover(issue), "page": p.page, "pages": issue.page_count})
    return reading[:limit]


@comics_blueprint.get("/add")
@login_required
def add_page():
    return _admin_page() or _page("add.html", "add", query=request.args.get("q", ""))


@comics_blueprint.get("/series/<int:series_id>")
@login_required
def series_page(series_id):
    series = _series_or_404(series_id)
    shown = series.issues if _is_admin() else [i for i in series.issues if i.filename]
    progress = _progress_by_issue(i.id for i in shown)
    issues = [issue_json(i, progress.get(i.id)) for i in reversed(shown)]
    return _page("series.html", "series", series=series, cover=_series_cover(series), issues=issues, monitor_choices=MONITOR_CHOICES)


@comics_blueprint.get("/downloads")
@login_required
def downloads_page():
    """Wanted issues, downloads, files to import and what's coming, together."""
    if not _is_admin():
        return redirect(url_for("comics.index"))
    today = date.today()
    soon = ComicIssue.query.filter(ComicIssue.filename.is_(None), db.or_(ComicIssue.store_date > today, db.and_(ComicIssue.store_date.is_(None), ComicIssue.cover_date > today))).all()
    soon = [i for i in soon if i.release_date and i.release_date <= today + timedelta(days=60) and i.series.monitor != "none"]
    soon.sort(key=lambda i: (i.release_date, i.series.name, i.sort_number))
    options = [[s.id, s.display_name] for s in ComicSeries.query.order_by(ComicSeries.name)]
    return _page(
        "downloads.html",
        "downloads",
        wanted=[issue_json(i) for i in downloads.wanted_issues()],
        upcoming=[issue_json(i) for i in soon],
        series_options=options,
        can_search=bool(settings.get("indexers")),
    )


@comics_blueprint.get("/settings")
@login_required
def settings_page():
    return _admin_page() or _page("settings.html", "settings", import_dir=files.import_dir(), comic_dir=files.comic_dir())


@comics_blueprint.get("/read/<int:issue_id>")
@login_required
def read_page(issue_id):
    issue = _issue_or_404(issue_id)
    if not issue.filename or not os.path.exists(files.abs_path(issue)):
        return redirect(url_for("comics.series_page", series_id=issue.series_id))
    if not issue.page_count:
        issue.page_count = archive.page_count(files.abs_path(issue))
        db.session.commit()
    progress = _progress_by_issue([issue.id]).get(issue.id)
    siblings = [i for i in issue.series.issues if i.filename]
    index = next((n for n, i in enumerate(siblings) if i.id == issue.id), 0)
    prev_issue = siblings[index - 1] if index > 0 else None
    next_issue = siblings[index + 1] if index + 1 < len(siblings) else None
    return render_template("comics/reader.html", issue=issue, series=issue.series, page=progress.page if progress and not progress.finished else 0, prev_issue=prev_issue, next_issue=next_issue)


# Files


@comics_blueprint.get("/issue/<int:issue_id>/page/<int:page>")
@login_required
def issue_page(issue_id, page):
    issue = _issue_or_404(issue_id)
    if not issue.filename:
        abort(404, description="No file for that issue")
    etag = f"{issue.id}-{issue.file_size}-{page}"
    if request.if_none_match.contains(etag):
        return "", 304
    try:
        data, mimetype = archive.read_page(files.abs_path(issue), page)
    except (IndexError, OSError):
        abort(404, description="No such page")
    response = make_response(data)
    response.headers["Content-Type"] = mimetype
    response.headers["Cache-Control"] = "private, max-age=31536000"
    response.set_etag(etag)
    return response


@comics_blueprint.get("/issue/<int:issue_id>/cover")
@login_required
def issue_cover(issue_id):
    """The first page as a WebP thumbnail, cached on disk."""
    issue = _issue_or_404(issue_id)
    if not issue.filename:
        if issue.cover_url:
            return redirect(issue.cover_url)
        abort(404, description="No cover")
    width = 300 if request.args.get("w", type=int, default=300) <= 300 else 600
    etag = f"c{issue.id}-{issue.file_size}-{width}"
    if request.if_none_match.contains(etag):
        return "", 304
    thumb_dir = current_app.config["THUMB_DIR"]
    path = os.path.join(thumb_dir, f"comic-{issue.id}-{issue.file_size}-{width}.webp")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        try:
            data = make_thumbnail(archive.first_page(files.abs_path(issue)), width)
        except Exception:
            abort(404, description="No cover")
        os.makedirs(thumb_dir, exist_ok=True)
        for old in os.listdir(thumb_dir):
            if old.startswith(f"comic-{issue.id}-") and not old.startswith(f"comic-{issue.id}-{issue.file_size}-"):
                os.remove(os.path.join(thumb_dir, old))
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    response = make_response(data)
    response.headers["Content-Type"] = "image/webp"
    response.headers["Cache-Control"] = "private, max-age=31536000"
    response.set_etag(etag)
    return response


@comics_blueprint.get("/issue/<int:issue_id>/download")
@login_required
def issue_download(issue_id):
    issue = _issue_or_404(issue_id)
    if not issue.filename or not os.path.exists(files.abs_path(issue)):
        abort(404, description="No file for that issue")
    return send_file(files.abs_path(issue), as_attachment=True, download_name=os.path.basename(issue.filename))


# API: series


@comics_blueprint.get("/api/lookup")
@json_admin_required
def lookup():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"results": []})
    try:
        provider = providers.get_provider(request.args.get("provider") or None)
        results = provider.search_series(query)
    except providers.ProviderError as e:
        return jsonify({"error": str(e)}), 502
    followed = {(s.provider, s.provider_id): s.id for s in ComicSeries.query.filter_by(provider=provider.name)}
    for row in results:
        row["followed_id"] = followed.get((row["provider"], row["provider_id"]))
    return jsonify({"results": results, "provider": provider.name})


@comics_blueprint.post("/api/series")
@json_admin_required
def create_series():
    data = request.get_json(silent=True) or {}
    monitor = data.get("monitor", "future")
    if monitor not in MONITOR_CHOICES:
        return jsonify({"error": "Pick all, future or none."}), 400
    try:
        series = add_series(data.get("provider", ""), str(data.get("provider_id", "")), monitor)
    except providers.ProviderError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 502
    if any(i.status == WANTED and i.released for i in series.issues):
        jobs.request_run("search")
    return jsonify({"id": series.id, "url": url_for("comics.series_page", series_id=series.id)}), 201


@comics_blueprint.patch("/api/series/<int:series_id>")
@json_admin_required
def update_series(series_id):
    series = _series_or_404(series_id)
    data = request.get_json(silent=True) or {}
    if "monitor" in data:
        if data["monitor"] not in MONITOR_CHOICES:
            return jsonify({"error": "Pick all, future or none."}), 400
        set_monitor(series, data["monitor"])
        if data["monitor"] != "none":
            jobs.request_run("search")
    return jsonify({"ok": True})


@comics_blueprint.post("/api/series/<int:series_id>/refresh")
@json_admin_required
def refresh(series_id):
    series = _series_or_404(series_id)
    try:
        added = refresh_series(series)
    except providers.ProviderError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 502
    return jsonify({"added": added})


@comics_blueprint.delete("/api/series/<int:series_id>")
@json_admin_required
def delete_series(series_id):
    series = _series_or_404(series_id)
    delete_files = request.args.get("files") == "1"
    removed = 0
    if delete_files:
        for issue in series.issues:
            if issue.filename:
                try:
                    os.remove(files.abs_path(issue))
                    removed += 1
                except OSError:
                    pass
        if series.folder:
            try:
                os.rmdir(os.path.join(files.comic_dir(), series.folder))
            except OSError:
                pass
    db.session.delete(series)
    db.session.commit()
    return jsonify({"ok": True, "files_removed": removed})


@comics_blueprint.post("/api/series/<int:series_id>/search")
@json_admin_required
def search_series_wanted(series_id):
    series = _series_or_404(series_id)
    cache, grabbed = {}, 0
    for issue in series.issues:
        if issue.status == WANTED and issue.released and downloads.search_issue(issue, cache):
            grabbed += 1
    return jsonify({"grabbed": grabbed})


# API: issues


@comics_blueprint.patch("/api/issues/<int:issue_id>")
@json_admin_required
def update_issue(issue_id):
    issue = _issue_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in (WANTED, SKIPPED):
        return jsonify({"error": "An issue can be set to wanted or skipped."}), 400
    if issue.filename:
        return jsonify({"error": "You already have that issue."}), 409
    issue.status = status
    db.session.commit()
    return jsonify(issue_json(issue))


@comics_blueprint.post("/api/issues/bulk")
@json_admin_required
def bulk_update_issues():
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in (WANTED, SKIPPED):
        return jsonify({"error": "Issues can be set to wanted or skipped."}), 400
    changed = 0
    for issue in ComicIssue.query.filter(ComicIssue.id.in_([int(i) for i in data.get("ids", [])])):
        if issue.filename or issue.status == SNATCHED:
            continue
        issue.status = status
        changed += 1
    db.session.commit()
    if status == WANTED and changed:
        jobs.request_run("search")
    return jsonify({"changed": changed})


@comics_blueprint.post("/api/issues/<int:issue_id>/search")
@json_admin_required
def search_issue(issue_id):
    """Grab the best release now."""
    issue = _issue_or_404(issue_id)
    if not settings.get("indexers"):
        return jsonify({"error": "Add an indexer in Settings first."}), 400
    releases, errors = downloads.find_releases(issue)
    best = next((r for r in releases if r.score >= 0), None)
    if best is None:
        return jsonify({"error": "; ".join(errors) or "Nothing on the indexers fits this issue yet.", "releases": len(releases)}), 404
    try:
        download = downloads.grab(issue, best)
    except clients.ClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"download": download_json(download), "issue": issue_json(issue)})


@comics_blueprint.get("/api/issues/<int:issue_id>/releases")
@json_admin_required
def issue_releases(issue_id):
    """Every release for an issue, to pick one by hand. The links stay on the
    server (they can carry indexer keys); grabbing names one by its token."""
    issue = _issue_or_404(issue_id)
    if not settings.get("indexers"):
        return jsonify({"error": "Add an indexer in Settings first."}), 400
    releases, errors = downloads.find_releases(issue)
    from .. import cache

    token = secrets.token_urlsafe(12)
    cache.set(f"comic-releases:{token}", {"issue_id": issue.id, "releases": [vars(r) for r in releases]}, timeout=1800)
    return jsonify({"token": token, "releases": [r.public() for r in releases], "errors": errors})


@comics_blueprint.post("/api/issues/<int:issue_id>/grab")
@json_admin_required
def grab_release(issue_id):
    issue = _issue_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    from .. import cache

    saved = cache.get(f"comic-releases:{data.get('token')}")
    if not saved or saved["issue_id"] != issue.id:
        return jsonify({"error": "That list is out of date; search again."}), 410
    try:
        release = indexers.Release(**saved["releases"][int(data.get("index", -1))])
    except (IndexError, ValueError, TypeError):
        return jsonify({"error": "No such release."}), 400
    try:
        download = downloads.grab(issue, release)
    except clients.ClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"download": download_json(download), "issue": issue_json(issue)})


@comics_blueprint.delete("/api/issues/<int:issue_id>/file")
@json_admin_required
def delete_issue_file(issue_id):
    issue = _issue_or_404(issue_id)
    files.delete_file(issue)
    return jsonify(issue_json(issue))


@comics_blueprint.post("/api/issues/<int:issue_id>/upload")
@json_admin_required
def upload_issue_file(issue_id):
    """A file for one issue, from your computer."""
    issue = _issue_or_404(issue_id)
    upload = request.files.get("file")
    if upload is None or not names.is_comic_file(upload.filename or ""):
        return jsonify({"error": "Choose a CBZ, CBR or CB7 file."}), 400
    folder = os.path.join(files.import_dir(), ".uploads")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, secure_filename(upload.filename) or "upload.cbz")
    upload.save(path)
    try:
        files.import_file(path, issue)
    except archive.ArchiveError as e:
        os.remove(path)
        return jsonify({"error": str(e)}), 400
    downloads.mark_imported([issue.id])
    return jsonify(issue_json(issue))


@comics_blueprint.put("/api/issues/<int:issue_id>/progress")
@json_login_required
def save_progress(issue_id):
    issue = _issue_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    progress = ComicProgress.query.filter_by(user_id=current_user.id, issue_id=issue.id).first()
    if progress is None:
        progress = ComicProgress(user_id=current_user.id, issue_id=issue.id)
        db.session.add(progress)
    progress.page = max(0, int(data.get("page", 0)))
    if "finished" in data:
        progress.finished = bool(data["finished"])
    elif issue.page_count and progress.page >= issue.page_count - 1:
        progress.finished = True
    db.session.commit()
    return jsonify({"page": progress.page, "finished": progress.finished})


# API: import folder


@comics_blueprint.get("/api/import")
@json_admin_required
def import_list():
    folder = files.import_dir()
    os.makedirs(folder, exist_ok=True)
    rows = []
    for path in files.comic_files(folder):
        match = files.match_file(path)
        rows.append({
            "path": os.path.relpath(path, folder),
            "size": os.path.getsize(path),
            "parsed": {"series": match.parsed.series, "number": match.parsed.number, "year": match.parsed.year},
            "issue": {"id": match.issue.id, "label": f"{match.series.display_name} #{match.issue.number}"} if match.issue else None,
            "series": {"id": match.series.id, "name": match.series.display_name} if match.series else None,
            "reason": match.reason,
        })
    return jsonify({"files": rows, "folder": folder})


@comics_blueprint.post("/api/import/upload")
@json_admin_required
def import_upload():
    """Files from your computer into the import folder, then matched."""
    folder = files.import_dir()
    os.makedirs(folder, exist_ok=True)
    saved = 0
    for upload in request.files.getlist("files"):
        if not names.is_comic_file(upload.filename or ""):
            continue
        # Keep the name as it was (it's what matching reads), just safely.
        name = names.safe_filename(os.path.basename(upload.filename))
        upload.save(os.path.join(folder, name))
        saved += 1
    if not saved:
        return jsonify({"error": "Choose CBZ, CBR or CB7 files."}), 400
    result = files.scan_import_dir()
    downloads.mark_imported(result["imported"])
    return jsonify({"saved": saved, **result})


@comics_blueprint.post("/api/import/scan")
@json_admin_required
def import_scan():
    result = files.scan_import_dir()
    downloads.mark_imported(result["imported"])
    return jsonify(result)


@comics_blueprint.post("/api/import/file")
@json_admin_required
def import_one():
    """Import one file as an issue you pick, or as a new local series when no
    provider knows it."""
    data = request.get_json(silent=True) or {}
    try:
        path = files.import_folder_path(data.get("path", ""))
    except FileNotFoundError:
        return jsonify({"error": "That file isn't in the import folder any more."}), 404
    if data.get("issue_id"):
        issue = _issue_or_404(int(data["issue_id"]))
    elif data.get("series_id") or data.get("new_series"):
        number = names.normalize_number(str(data.get("number") or "")) or names.parse(os.path.basename(path)).number
        if not number:
            return jsonify({"error": "Which issue number is it?"}), 400
        if data.get("series_id"):
            series = _series_or_404(int(data["series_id"]))
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
        files.import_file(path, issue)
    except archive.ArchiveError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    downloads.mark_imported([issue.id])
    return jsonify(issue_json(issue))


@comics_blueprint.delete("/api/import/file")
@json_admin_required
def import_delete():
    try:
        path = files.import_folder_path(request.args.get("path", ""))
    except FileNotFoundError:
        return jsonify({"ok": True})
    os.remove(path)
    return jsonify({"ok": True})


# API: downloads and jobs


@comics_blueprint.get("/api/activity")
@json_admin_required
def activity():
    active = ComicDownload.query.filter(ComicDownload.status.in_(DL_ACTIVE)).order_by(ComicDownload.created_at.desc()).all()
    history = ComicDownload.query.filter(~ComicDownload.status.in_(DL_ACTIVE)).order_by(ComicDownload.updated_at.desc()).limit(100).all()
    return jsonify({"active": [download_json(d) for d in active], "history": [download_json(d) for d in history], "worker": jobs.status()})


@comics_blueprint.post("/api/jobs/<job>")
@json_admin_required
def run_job(job):
    if job not in jobs.JOBS:
        abort(404)
    jobs.request_run(job)
    return jsonify({"ok": True})


@comics_blueprint.post("/api/downloads/<int:download_id>/cancel")
@json_admin_required
def cancel_download(download_id):
    download = db.session.get(ComicDownload, download_id) or abort(404)
    downloads.cancel(download)
    return jsonify(download_json(download))


@comics_blueprint.post("/api/downloads/<int:download_id>/retry")
@json_admin_required
def retry_download(download_id):
    """Block this release and look for another."""
    download = db.session.get(ComicDownload, download_id) or abort(404)
    if download.status in DL_ACTIVE:
        downloads.cancel(download)
    download.status = DL_FAILED
    if download.issue and download.issue.status != DOWNLOADED:
        download.issue.status = WANTED
    db.session.commit()
    if download.issue is None:
        return jsonify({"error": "That issue is gone."}), 404
    grabbed = downloads.search_issue(download.issue)
    if grabbed is None:
        return jsonify({"error": "Nothing else fits this issue yet; it stays wanted."}), 404
    return jsonify(download_json(grabbed))


@comics_blueprint.delete("/api/downloads/<int:download_id>")
@json_admin_required
def forget_download(download_id):
    """Remove a finished or failed download from the history (and the blocklist)."""
    download = db.session.get(ComicDownload, download_id) or abort(404)
    if download.status in DL_ACTIVE:
        return jsonify({"error": "Cancel it first."}), 409
    db.session.delete(download)
    db.session.commit()
    return jsonify({"ok": True})


# API: settings


def _merge_secret(new, old):
    return old if settings.is_masked(new) else new


@comics_blueprint.get("/api/settings")
@json_admin_required
def get_settings():
    return jsonify(settings.for_browser())


@comics_blueprint.put("/api/settings")
@json_admin_required
def put_settings():
    """Save settings. Masked secrets ("••••1234") mean "unchanged"."""
    data = request.get_json(silent=True) or {}
    current = settings.get_all()
    for key in settings.SECRETS:
        if key in data:
            data[key] = _merge_secret(data[key], current[key])
    if "indexers" in data:
        old = {(i.get("name"), i.get("url")): i for i in current["indexers"]}
        cleaned = []
        for indexer in data["indexers"]:
            if not (indexer.get("url") or "").strip():
                continue
            previous = old.get((indexer.get("name"), indexer.get("url")), {})
            cleaned.append({
                "name": (indexer.get("name") or "").strip() or indexer["url"],
                "kind": "torznab" if indexer.get("kind") == "torznab" else "newznab",
                "url": indexer["url"].strip(),
                "api_key": _merge_secret(indexer.get("api_key", ""), previous.get("api_key", "")),
                "categories": (indexer.get("categories") or indexers.COMICS_CATEGORY).strip(),
                "enabled": bool(indexer.get("enabled", True)),
            })
        data["indexers"] = cleaned
    if "sabnzbd" in data:
        data["sabnzbd"]["api_key"] = _merge_secret(data["sabnzbd"].get("api_key", ""), current["sabnzbd"].get("api_key", ""))
    if "qbittorrent" in data:
        data["qbittorrent"]["password"] = _merge_secret(data["qbittorrent"].get("password", ""), current["qbittorrent"].get("password", ""))
    for key in ("preferred_words", "rejected_words"):
        if isinstance(data.get(key), str):
            data[key] = [w.strip() for w in data[key].split(",") if w.strip()]
    settings.set_many(data)
    return jsonify(settings.for_browser())


@comics_blueprint.post("/api/settings/test")
@json_admin_required
def test_settings():
    """Try a provider, indexer or client with the settings as saved."""
    data = request.get_json(silent=True) or {}
    what = data.get("what")
    try:
        if what == "comicvine":
            providers.ComicVine(settings.get("comicvine_api_key")).search_series("batman")
            message = "ComicVine answered."
        elif what == "metron":
            providers.Metron(settings.get("metron_username"), settings.get("metron_password")).search_series("batman")
            message = "Metron answered."
        elif what == "indexer":
            indexer = settings.get("indexers")[int(data.get("index", 0))]
            message = indexers.test(indexer)
        elif what == "sabnzbd":
            message = clients.SABnzbd(settings.get("sabnzbd")).test()
        elif what == "qbittorrent":
            message = clients.QBittorrent(settings.get("qbittorrent")).test()
        elif what == "blackhole":
            message = clients.Blackhole(settings.get("blackhole_dir")).test()
        else:
            return jsonify({"error": "Test what?"}), 400
    except (providers.ProviderError, indexers.IndexerError, clients.ClientError) as e:
        return jsonify({"error": str(e)}), 502
    except (IndexError, ValueError):
        return jsonify({"error": "Save it first."}), 400
    return jsonify({"message": message})
