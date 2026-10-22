"""Comics pages and their JSON API, under /comics/.

Anyone signed in can read the comics there are files for. Following series,
downloading, importing and settings are for admins.
"""

import os
from datetime import date

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

from ..downloads import clients, jobs
from ..downloads.models import SKIPPED, SNATCHED, WANTED
from ..models import db
from ..routes._helpers import json_admin_required, json_login_required
from ..utils import make_thumbnail
from . import (
    archive,
    downloads,
    files,
    names,
    providers,
)
from .models import MONITOR_CHOICES, ComicIssue, ComicProgress, ComicSeries
from .series import add_series, refresh_series, set_monitor

comics_blueprint = Blueprint("comics", __name__, url_prefix="/comics", template_folder="../templates")

MONITOR_ERROR = "Choose New issues, All missing or None."


@comics_blueprint.app_template_filter("comic_date")
def comic_date(value) -> str:
    """"19 Aug" this year, "19 Aug 2025" otherwise; takes a date or an ISO string."""
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {value:%b}" + ("" if value.year == date.today().year else f" {value.year}")


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


def _page(template: str, **context):
    return render_template(f"comics/{template}", **context)


# Pages


VIEWS = ("all", "unread", "reading", "finished")


def _up_next(have: list, mine: dict):
    """The issue to open: the one you're partway through (the latest, if
    several), else the first you haven't finished, else the first. Returns
    (issue, its progress if started)."""
    started = sorted((p for p in mine.values() if not p.finished and p.page > 0), key=lambda p: p.updated_at, reverse=True)
    if started:
        return next(i for i in have if i.id == started[0].issue_id), started[0]
    return next((i for i in have if not (i.id in mine and mine[i.id].finished)), have[0] if have else None), None


def _series_card(series: ComicSeries, progress: dict) -> dict:
    """A series on the wall, as books are: where the cover takes you, how far
    you are, and which of All / Unread / Reading / Finished it falls under."""
    have = [i for i in series.issues if i.filename]
    mine = {i.id: progress[i.id] for i in have if i.id in progress}
    finished = sum(1 for p in mine.values() if p.finished)
    last = max((p.updated_at for p in mine.values()), default=None)
    issue, started = _up_next(have, mine)
    if not have:
        state, line = "unread", "No issues yet"
    elif started:
        pct = int(100 * (started.page + 1) / issue.page_count) if issue.page_count else None
        state, line = "reading", f"#{issue.number}" + (f" · {pct}%" if pct else "")
    elif finished == len(have):
        state, line = "finished", f"All {len(have)} read" if len(have) > 1 else "Read"
    else:
        state = "reading" if finished else "unread"
        line = f"{finished} of {len(have)} read" if finished else (f"{len(have)} issues" if len(have) > 1 else "1 issue")
    if issue is None:
        href, label = url_for("comics.series_page", series_id=series.id), series.display_name
    else:
        href = url_for("comics.read_page", issue_id=issue.id)
        label = f"{'Continue' if started else 'Read'} {series.name} #{issue.number}"
    return {"series": series, "cover": _series_cover(series), "href": href, "label": label, "state": state, "line": line, "last": last.isoformat() if last else ""}


@comics_blueprint.get("/")
@login_required
def index():
    """The wall of series. Like the books, it opens on what you're reading
    when there's something, else on everything; ?view= picks explicitly."""
    admin = _is_admin()
    progress = {p.issue_id: p for p in ComicProgress.query.filter_by(user_id=current_user.id)}
    cards = [_series_card(s, progress) for s in ComicSeries.query.order_by(ComicSeries.name) if admin or any(i.filename for i in s.issues)]
    view = request.args.get("view")
    if view not in VIEWS:
        view = "reading" if any(c["state"] == "reading" for c in cards) else "all"
    return _page("index.html", cards=cards, current_view=view)


@comics_blueprint.get("/series/<int:series_id>")
@login_required
def series_page(series_id):
    series = _series_or_404(series_id)
    admin = _is_admin()
    shown = series.issues if admin else [i for i in series.issues if i.filename]
    progress = _progress_by_issue(i.id for i in shown)
    # Reading order for everyone; admins sort out missing ones with Have / Missing.
    issues = [issue_json(i, progress.get(i.id)) for i in shown]
    have = [i for i in series.issues if i.filename]
    up_next = None
    if have:
        next_issue = _up_next(have, {i.id: progress[i.id] for i in have if i.id in progress})[0]
        up_next = next(i for i in issues if i["id"] == next_issue.id)
    pending = series.refreshed_at is None and series.provider in ("comicvine", "metron")
    return _page("series.html", series=series, cover=_series_cover(series), issues=issues, up_next=up_next, pending=pending)


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


@comics_blueprint.post("/api/series")
@json_admin_required
def create_series():
    data = request.get_json(silent=True) or {}
    monitor = data.get("monitor", "future")
    if monitor not in MONITOR_CHOICES:
        return jsonify({"error": MONITOR_ERROR}), 400
    try:
        # The series now; its issues come with the worker's refresh (which
        # asks for a search if any are wanted), so following doesn't wait.
        series = add_series(data.get("provider", ""), str(data.get("provider_id", "")), monitor, fetch_issues=False)
    except providers.ProviderError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 502
    jobs.request_run("refresh")
    return jsonify({"id": series.id, "url": url_for("comics.series_page", series_id=series.id)}), 201


@comics_blueprint.get("/api/series/<int:series_id>")
@json_login_required
def series_state(series_id):
    """Whether a just-followed series has its issues yet."""
    series = _series_or_404(series_id)
    return jsonify({"pending": series.refreshed_at is None and series.provider in ("comicvine", "metron"), "issues": len(series.issues)})


@comics_blueprint.patch("/api/series/<int:series_id>")
@json_admin_required
def update_series(series_id):
    series = _series_or_404(series_id)
    data = request.get_json(silent=True) or {}
    wanted = None
    if "monitor" in data:
        if data["monitor"] not in MONITOR_CHOICES:
            return jsonify({"error": MONITOR_ERROR}), 400
        wanted = set_monitor(series, data["monitor"])
        if data["monitor"] != "none":
            jobs.request_run("search")
    return jsonify({"monitor": series.monitor, "wanted": wanted})


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
    cache, grabbed, error = {}, 0, None
    for issue in series.issues:
        if issue.status != WANTED or not issue.released:
            continue
        try:
            if downloads.search_issue(issue, cache, raise_client_errors=True):
                grabbed += 1
        except clients.ClientError as e:
            error = str(e)
            break
    return jsonify({"grabbed": grabbed, "error": error})


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


