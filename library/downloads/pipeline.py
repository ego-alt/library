"""Finding wanted things on the indexers, grabbing the best release, and
following the download until its file is in the library: the same for books
and comics.

What differs by kind lives in a handler (comics/downloads.py, books/getting.py)
registered here, which says:
  wanted()                 what's wanted and out, newest first
  queries(item)            what to ask the indexers for
  score(release, item, opts, blocked)
                           how well a release fits (None when it doesn't,
                           with release.note saying why)
  import_files(download, paths, keep)
                           put a finished download's files in the library,
                           raising ImportFilesError when it can't
  label(item), link(item)  for the Downloads page
and `fk`, the Download column that points at its items.
"""

import logging
import os
import shutil
from datetime import timedelta

from .. import settings
from ..models import _utcnow, db
from . import clients, indexers
from .models import (
    DL_ACTIVE,
    DL_DONE,
    DL_DOWNLOADING,
    DL_FAILED,
    DL_IMPORTING,
    SNATCHED,
    WANTED,
    Download,
)

logger = logging.getLogger(__name__)

# A blackhole grab that hasn't shown up in the import folder by then has failed.
BLACKHOLE_GIVE_UP = timedelta(days=3)

_handlers: dict = {}


class ImportFilesError(Exception):
    pass


def register(handler) -> None:
    _handlers[handler.name] = handler


def handler(kind: str):
    return _handlers[kind]


def handlers() -> list:
    return list(_handlers.values())


def find_releases(kind: str, item, cache: dict | None = None) -> tuple[list[indexers.Release], list[str]]:
    """Every release the indexers have for an item, best first, with the ones
    that don't fit at the end. Also returns indexer errors.

    Each indexer is asked the kind's queries in turn (the broadest first, so
    one search covers many comic issues; `cache` shares it across a run),
    stopping at the first that finds something that fits."""
    kind_handler = handler(kind)
    opts = settings.get_all()
    cache = cache if cache is not None else {}
    blocked = {d.title for d in Download.query.filter_by(status=DL_FAILED, **{kind_handler.fk: item.id})}
    found, errors = [], []
    for indexer in opts["indexers"]:
        if not indexer.get("enabled", True) or not indexer.get("url"):
            continue
        if not clients.can_download("torrent" if indexer.get("kind") == "torznab" else "usenet"):
            continue
        for query in kind_handler.queries(item):
            key = (indexer.get("name"), indexer.get("url"), kind, query)
            if key not in cache:
                try:
                    cache[key] = indexers.search(indexer, query, kind)
                except indexers.IndexerError as e:
                    cache[key] = []
                    errors.append(str(e))
            results = [indexers.Release(**vars(r)) for r in cache[key]]
            for release in results:
                score = kind_handler.score(release, item, opts, blocked)
                release.score = score if score is not None else -1
            found.extend(results)
            if any(r.score >= 0 for r in results):
                break
    unique = {}
    for release in found:
        if release.title not in unique or release.score > unique[release.title].score:
            unique[release.title] = release
    return sorted(unique.values(), key=lambda r: r.score, reverse=True), errors


def grab(kind: str, item, release: indexers.Release) -> Download:
    """Send a release to its download client."""
    download = Download(kind=kind, title=release.title, indexer=release.indexer, protocol=release.protocol, url=release.url, size=release.size, **{handler(kind).fk: item.id})
    db.session.add(download)
    db.session.flush()
    try:
        client = clients.client_for(release.protocol)
        download.client = client.name
        download.client_ref = client.add(release.url, release.title, download.id, release.protocol, kind)
    except clients.ClientError as e:
        download.status = DL_FAILED
        download.error = str(e)
        db.session.commit()
        raise
    download.status = DL_DOWNLOADING
    item.status = SNATCHED
    db.session.commit()
    return download


def search_item(kind: str, item, cache: dict | None = None, *, raise_client_errors: bool = False) -> Download | None:
    """Grab the best release for a wanted item, if there is one. A download
    client that can't take it is logged (the failed grab stays in the
    history), or raised with raise_client_errors."""
    releases, _errors = find_releases(kind, item, cache)
    item.searched_at = _utcnow()
    db.session.commit()
    best = next((r for r in releases if r.score >= 0), None)
    if best is None:
        return None
    try:
        return grab(kind, item, best)
    except clients.ClientError as e:
        if raise_client_errors:
            raise
        logger.warning("Couldn't grab %s: %s", best.title, e)
        return None


def search_wanted(limit: int = 50) -> int:
    """Search for everything wanted, the longest-waiting first (`limit` of
    each kind per run, so a long list is worked through over several runs).
    Returns how many were grabbed."""
    if not settings.get("indexers"):
        return 0
    grabbed = 0
    for kind_handler in handlers():
        cache = {}
        waiting = sorted(kind_handler.wanted(), key=lambda i: (i.searched_at is not None, i.searched_at or 0))
        for item in waiting[:limit]:
            if search_item(kind_handler.name, item, cache):
                grabbed += 1
    return grabbed


def fail(download: Download, error: str) -> None:
    download.status = DL_FAILED
    download.error = error
    item = download.item
    if item is not None and item.status == SNATCHED:
        item.status = WANTED
    db.session.commit()


def _files_in(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    found = []
    for root, _dirs, names in os.walk(path):
        found.extend(os.path.join(root, name) for name in names if not name.startswith("."))
    return sorted(found)


def finish(download: Download, path: str | None) -> None:
    """Import a finished download's files into the library."""
    download.status = DL_IMPORTING
    download.path = path
    db.session.commit()
    if not path or not os.path.exists(path):
        fail(download, f"The client says it's done, but {path or 'its folder'} isn't visible here. Check where finished downloads are, in Settings.")
        return
    # A torrent keeps seeding from its files, so they're copied, not moved.
    keep = download.protocol == "torrent"
    try:
        handler(download.kind).import_files(download, _files_in(path), keep)
    except ImportFilesError as e:
        fail(download, str(e))
        return
    except Exception as e:
        logger.exception("Importing %s failed", path)
        db.session.rollback()
        fail(download, f"Couldn't import it: {e}")
        return
    if not keep and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    download.status = DL_DONE
    download.progress = 1.0
    db.session.commit()


# Download clients that didn't answer at the last check: {name: message}.
# The Downloads page says so once, rather than under every download.
client_problems: dict[str, str] = {}

# A download whose progress hasn't moved for this long is called stalled.
STALLED_AFTER = timedelta(hours=6)


def is_stalled(download: Download) -> bool:
    return download.status == DL_DOWNLOADING and download.client != "blackhole" and download.updated_at is not None and _utcnow().replace(tzinfo=None) - download.updated_at > STALLED_AFTER


def check_downloads() -> int:
    """Ask the clients about active downloads; import finished ones. Returns
    how many are still active."""
    client_problems.clear()
    for download in Download.query.filter(Download.status.in_(DL_ACTIVE)).all():
        if download.client == "blackhole":
            if _utcnow().replace(tzinfo=None) - download.created_at > BLACKHOLE_GIVE_UP:
                fail(download, "Its file never showed up in the import folder.")
            continue
        if download.status == DL_IMPORTING:
            continue
        try:
            state = clients.client_for(download.protocol, download.client).state(download.client_ref)
        except clients.ClientError as e:
            client_problems[download.client or download.protocol or "client"] = str(e)
            continue
        if state.state == "downloading":
            download.progress = state.progress
            download.error = None
            db.session.commit()
        elif state.state == "done":
            finish(download, state.path)
        else:
            fail(download, state.error or "The download failed.")
    return active_count()


def active_count() -> int:
    return Download.query.filter(Download.status.in_(DL_ACTIVE)).count()


def mark_imported(kind: str, item_ids: list[int]) -> None:
    """Downloads whose item arrived another way (a blackhole, or by hand) are done."""
    if not item_ids:
        return
    column = getattr(Download, handler(kind).fk)
    for download in Download.query.filter(column.in_(item_ids), Download.status.in_(DL_ACTIVE)):
        download.status = DL_DONE
        download.progress = 1.0
    db.session.commit()


def cancel(download: Download) -> None:
    try:
        clients.client_for(download.protocol, download.client).remove(download.client_ref)
    except clients.ClientError:
        pass
    fail(download, "Cancelled.")


def retry(download: Download) -> Download | None:
    """Block this release and grab the next best, if any."""
    if download.status in DL_ACTIVE:
        cancel(download)
    download.status = DL_FAILED
    item = download.item
    if item is not None and item.status != "downloaded":
        item.status = WANTED
    db.session.commit()
    return search_item(download.kind, item) if item is not None else None
