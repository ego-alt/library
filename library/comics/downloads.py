"""Finding wanted issues on indexers, grabbing the best release, and
following the download until its file is in the library."""

import logging
import os
import shutil
from datetime import timedelta

from ..models import _utcnow, db
from . import clients, files, indexers, names, settings
from .models import (
    DL_ACTIVE,
    DL_DONE,
    DL_DOWNLOADING,
    DL_FAILED,
    DL_IMPORTING,
    SNATCHED,
    WANTED,
    ComicDownload,
    ComicIssue,
    ComicSeries,
)

logger = logging.getLogger(__name__)

# A blackhole grab that hasn't shown up in the import folder by then has failed.
BLACKHOLE_GIVE_UP = timedelta(days=3)


def _issue_year(issue: ComicIssue) -> int | None:
    when = issue.cover_date or issue.store_date
    return when.year if when else None


def score_release(release: indexers.Release, issue: ComicIssue, opts: dict, blocked: set[str]) -> float | None:
    """How good a release is for an issue, or None when it isn't that issue.
    Sets release.note to why, for the manual search list."""
    series = issue.series
    if release.title in blocked:
        release.note = "Failed before"
        return None
    parsed = names.parse(release.title)
    if parsed.trade:
        release.note = "A collection"
        return None
    if parsed.number is None or parsed.number != names.normalize_number(issue.number):
        release.note = f"Issue #{parsed.number}" if parsed.number else "No issue number"
        return None
    if parsed.annual != ("annual" in series.name.lower()):
        release.note = "Annual" if parsed.annual else "Not the annual"
        return None
    similarity = names.series_similarity(parsed.series, series.name)
    if similarity < files.SERIES_MATCH:
        release.note = f"Another series ({parsed.series})"
        return None
    years = {y for y in (_issue_year(issue), series.start_year) if y}
    if parsed.year and years and min(abs(parsed.year - y) for y in years) > 1:
        release.note = f"From {parsed.year}"
        return None
    title = release.title.lower()
    rejected = next((w for w in opts["rejected_words"] if w and w.lower() in title), None)
    if rejected:
        release.note = f"Has “{rejected}”"
        return None
    max_size = int(opts.get("max_size_mb") or 0) * 1024 * 1024
    if max_size and release.size and release.size > max_size:
        release.note = "Too big"
        return None
    if release.protocol == "torrent" and release.seeders == 0:
        release.note = "No seeders"
        return None
    score = similarity
    score += sum(0.1 for w in opts["preferred_words"] if w and w.lower() in title)
    if parsed.year and parsed.year in years:
        score += 0.05
    if release.seeders:
        score += min(release.seeders, 50) / 1000
    release.note = ""
    return score


def _query_name(series: ComicSeries) -> str:
    return " ".join(series.name.replace(":", " ").replace("/", " ").split())


def find_releases(issue: ComicIssue, cache: dict | None = None) -> tuple[list[indexers.Release], list[str]]:
    """Every release the indexers have for an issue, best first, with the ones
    that don't fit at the end. Also returns indexer errors.

    Each indexer is asked for the series by name (one search covers many
    issues, and `cache` shares it across a run), then, if that finds nothing,
    for the series and the zero-padded number."""
    opts = settings.get_all()
    cache = cache if cache is not None else {}
    blocked = {d.title for d in ComicDownload.query.filter_by(issue_id=issue.id, status=DL_FAILED)}
    found, errors = [], []
    for indexer in opts["indexers"]:
        if not indexer.get("enabled", True) or not indexer.get("url"):
            continue
        if not clients.can_download("torrent" if indexer.get("kind") == "torznab" else "usenet"):
            continue
        queries = [_query_name(issue.series)]
        number = names.normalize_number(issue.number) or ""
        queries.append(f"{queries[0]} {number.zfill(3) if number.isdigit() else number}")
        for query in queries:
            key = (indexer.get("name"), indexer.get("url"), query)
            if key not in cache:
                try:
                    cache[key] = indexers.search(indexer, query)
                except indexers.IndexerError as e:
                    cache[key] = []
                    errors.append(str(e))
            results = [indexers.Release(**vars(r)) for r in cache[key]]
            for release in results:
                score = score_release(release, issue, opts, blocked)
                release.score = score if score is not None else -1
            found.extend(results)
            if any(r.score >= 0 for r in results):
                break
    unique = {}
    for release in found:
        if release.title not in unique or release.score > unique[release.title].score:
            unique[release.title] = release
    return sorted(unique.values(), key=lambda r: r.score, reverse=True), errors


def grab(issue: ComicIssue, release: indexers.Release) -> ComicDownload:
    """Send a release to its download client."""
    download = ComicDownload(issue=issue, title=release.title, indexer=release.indexer, protocol=release.protocol, url=release.url, size=release.size)
    db.session.add(download)
    db.session.flush()
    try:
        client = clients.client_for(release.protocol)
        download.client = client.name
        download.client_ref = client.add(release.url, release.title, download.id, release.protocol)
    except clients.ClientError as e:
        download.status = DL_FAILED
        download.error = str(e)
        db.session.commit()
        raise
    download.status = DL_DOWNLOADING
    issue.status = SNATCHED
    db.session.commit()
    return download


def search_issue(issue: ComicIssue, cache: dict | None = None) -> ComicDownload | None:
    """Grab the best release for a wanted issue, if there is one."""
    releases, _errors = find_releases(issue, cache)
    best = next((r for r in releases if r.score >= 0), None)
    if best is None:
        return None
    try:
        return grab(issue, best)
    except clients.ClientError as e:
        logger.warning("Couldn't grab %s: %s", best.title, e)
        return None


def wanted_issues() -> list[ComicIssue]:
    """Wanted issues that are out, newest first."""
    issues = ComicIssue.query.filter_by(status=WANTED).all()
    return sorted((i for i in issues if i.released), key=lambda i: i.release_date or i.added_at.date(), reverse=True)


def search_wanted(limit: int = 50) -> int:
    """Search for wanted issues. Returns how many were grabbed."""
    if not settings.get("indexers"):
        return 0
    cache, grabbed = {}, 0
    for issue in wanted_issues()[:limit]:
        if search_issue(issue, cache):
            grabbed += 1
    return grabbed


def _fail(download: ComicDownload, error: str) -> None:
    download.status = DL_FAILED
    download.error = error
    if download.issue and download.issue.status == SNATCHED:
        download.issue.status = WANTED
    db.session.commit()


def _finish(download: ComicDownload, path: str | None) -> None:
    """Import a finished download's file into the library."""
    download.status = DL_IMPORTING
    download.path = path
    db.session.commit()
    if not path or not os.path.exists(path):
        _fail(download, f"The client says it's done, but {path or 'its folder'} isn't visible here. Check the path mapping in Settings.")
        return
    found = [path] if os.path.isfile(path) else files.comic_files(path)
    found = [f for f in found if names.is_comic_file(f)]
    if not found:
        _fail(download, "The download has no comic file in it.")
        return
    # A torrent keeps seeding from its files, so they're copied, not moved.
    keep = download.protocol == "torrent"
    target = download.issue
    try:
        if len(found) == 1 and target is not None:
            files.import_file(found[0], target, remove_source=not keep)
        else:
            for file in found:
                match = files.match_file(file)
                if match.issue:
                    files.import_file(file, match.issue, remove_source=not keep)
    except Exception as e:
        logger.exception("Importing %s failed", path)
        _fail(download, f"Couldn't import it: {e}")
        return
    if target is not None and not target.filename:
        _fail(download, "None of its files matched the issue.")
        return
    if not keep and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    download.status = DL_DONE
    download.progress = 1.0
    db.session.commit()


def check_downloads() -> int:
    """Ask the clients about active downloads; import finished ones. Returns
    how many are still active."""
    active = ComicDownload.query.filter(ComicDownload.status.in_(DL_ACTIVE)).all()
    for download in active:
        if download.client == "blackhole":
            if _utcnow().replace(tzinfo=None) - download.created_at > BLACKHOLE_GIVE_UP:
                _fail(download, "Its file never showed up in the import folder.")
            continue
        if download.status == DL_IMPORTING:
            continue
        try:
            client = clients.client_for(download.protocol, download.client)
            state = client.state(download.client_ref)
        except clients.ClientError as e:
            download.error = str(e)
            db.session.commit()
            continue
        if state.state == "downloading":
            download.progress = state.progress
            download.error = None
            db.session.commit()
        elif state.state == "done":
            _finish(download, state.path)
        else:
            _fail(download, state.error or "The download failed.")
    return ComicDownload.query.filter(ComicDownload.status.in_(DL_ACTIVE)).count()


def mark_imported(issue_ids: list[int]) -> None:
    """Downloads whose issue arrived another way (blackhole, or by hand) are done."""
    if not issue_ids:
        return
    for download in ComicDownload.query.filter(ComicDownload.issue_id.in_(issue_ids), ComicDownload.status.in_(DL_ACTIVE)):
        download.status = DL_DONE
        download.progress = 1.0
    db.session.commit()


def cancel(download: ComicDownload) -> None:
    try:
        clients.client_for(download.protocol, download.client).remove(download.client_ref)
    except clients.ClientError:
        pass
    _fail(download, "Cancelled.")
