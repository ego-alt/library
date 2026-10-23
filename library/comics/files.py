"""Comic files: matching them to issues, and bringing them into COMIC_DIR.

A file arrives as a finished download (for the issue it was started for) or
from a shelf's + (checked by hand first). It's matched to an issue of a
followed series by its ComicInfo.xml or its name, and written into the
library as a tagged CBZ at <Publisher>/<Series (Year)>/<Series> #<001>
(<Year>).cbz.
"""

import logging
import os
from dataclasses import dataclass

from flask import current_app

from .. import settings
from ..downloads.models import DOWNLOADED, SKIPPED
from ..models import db
from . import archive, names
from .models import ComicIssue, ComicSeries

logger = logging.getLogger(__name__)

# How alike a file's series name must be to a followed series' name.
SERIES_MATCH = 0.86


def comic_dir() -> str:
    return current_app.config["COMIC_DIR"]


def abs_path(issue: ComicIssue) -> str:
    return os.path.join(comic_dir(), issue.filename)


def series_folder(series: ComicSeries) -> str:
    if series.folder:
        return series.folder
    name = names.safe_filename(series.display_name)
    publisher = names.safe_filename(series.publisher) if series.publisher else "Unknown publisher"
    return os.path.join(publisher, name)


def issue_filename(series: ComicSeries, issue: ComicIssue) -> str:
    number = issue.number
    if number.lstrip("-").isdigit():
        number = number.zfill(3) if not number.startswith("-") else number
    when = issue.cover_date or issue.store_date
    year = f" ({when.year})" if when else (f" ({series.start_year})" if series.start_year else "")
    return names.safe_filename(f"{series.name} #{number}{year}") + ".cbz"


@dataclass
class Match:
    issue: ComicIssue | None
    series: ComicSeries | None
    parsed: names.ParsedName
    reason: str = ""


def _best_series(name: str, year: int | None, volume: int | None) -> ComicSeries | None:
    best, best_score = None, 0.0
    for series in ComicSeries.query.all():
        score = names.series_similarity(name, series.name)
        if score < SERIES_MATCH:
            continue
        # Several volumes share a name: the year, then the volume, picks one.
        if year and series.start_year:
            gap = year - series.start_year
            score += 0.1 if 0 <= gap <= 1 else (0.03 if 0 <= gap <= 12 else -0.2)
        if volume and series.volume:
            score += 0.05 if volume == series.volume else -0.05
        if score > best_score:
            best, best_score = series, score
    return best


def match_file(path: str) -> Match:
    """Which issue a comic file is, if any. ComicInfo.xml beats the filename."""
    parsed = names.parse(os.path.basename(path))
    info = archive.read_comicinfo(path) if path.lower().endswith((".cbz", ".zip")) else {}
    if info.get("Series") and info.get("Number"):
        parsed.series = info["Series"]
        parsed.number = names.normalize_number(info["Number"])
        if info.get("Year", "").isdigit():
            parsed.year = parsed.year or int(info["Year"])
    if not parsed.series:
        return Match(None, None, parsed, "Couldn't read a series name from it.")
    if parsed.number is None:
        return Match(None, None, parsed, "Couldn't read an issue number (a trade or collection?).")
    series = _best_series(parsed.series, parsed.year, parsed.volume)
    if series is None:
        return Match(None, None, parsed, f"No followed series looks like “{parsed.series}”.")
    issue = next((i for i in series.issues if names.normalize_number(i.number) == parsed.number), None)
    if issue is None:
        return Match(None, series, parsed, f"{series.display_name} has no issue #{parsed.number}.")
    return Match(issue, series, parsed)


def import_file(src: str, issue: ComicIssue, *, remove_source: bool = True) -> ComicIssue:
    """Write `src` into the library as `issue`'s file, replacing any older file."""
    series = issue.series
    opts = settings.get_all()
    original = os.path.basename(src)
    folder = series_folder(series)
    filename = os.path.join(folder, issue_filename(series, issue)) if opts["rename"] else os.path.join(folder, names.safe_filename(names.strip_extension(original)) + ".cbz")
    dest = os.path.join(comic_dir(), filename)

    old = abs_path(issue) if issue.filename else None
    tmp_dest = f"{dest}.new"
    try:
        pages = archive.write_cbz(src, tmp_dest, metadata=lambda pages: (archive.comicinfo_xml(issue, series, pages, original), archive.metroninfo_xml(issue, series, pages, original)))
        os.replace(tmp_dest, dest)
    finally:
        if os.path.exists(tmp_dest):
            os.remove(tmp_dest)
    if old and os.path.abspath(old) != os.path.abspath(dest) and os.path.exists(old):
        os.remove(old)

    series.folder = folder
    issue.filename = filename
    issue.file_size = os.path.getsize(dest)
    issue.page_count = pages
    issue.original_filename = original
    issue.status = DOWNLOADED
    db.session.commit()
    if remove_source and os.path.abspath(src) != os.path.abspath(dest):
        try:
            os.remove(src)
        except OSError as e:
            logger.warning("Imported %s but couldn't remove it: %s", src, e)
    # Its pages become WebP in the background, so adding it doesn't wait.
    from ..downloads import jobs

    try:
        jobs.request_run("convert")
    except OSError:
        pass
    return issue


def convert_next(limit: int = 3, pause: float = 0.05) -> tuple[int, bool]:
    """Convert up to `limit` issues whose pages aren't all WebP yet. Returns
    (how many were converted, whether more are waiting)."""
    done = 0
    for issue in ComicIssue.query.filter(ComicIssue.filename.isnot(None)).order_by(ComicIssue.added_at.desc()):
        path = abs_path(issue)
        if not os.path.isfile(path) or not archive.needs_webp(path):
            continue
        if done == limit:
            return done, True
        filename = issue.filename
        if archive.convert_pages(path, pause=pause):
            db.session.refresh(issue)
            if issue.filename == filename:
                issue.file_size = os.path.getsize(path)
                db.session.commit()
        done += 1
    return done, False


def delete_file(issue: ComicIssue) -> None:
    if issue.filename:
        try:
            os.remove(abs_path(issue))
        except OSError:
            pass
    issue.filename = None
    issue.file_size = None
    issue.page_count = None
    issue.status = SKIPPED
    db.session.commit()
