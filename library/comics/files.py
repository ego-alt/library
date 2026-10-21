"""Comic files: matching them to issues, and bringing them into COMIC_DIR.

Files arrive in the import folder (finished downloads, or anything dropped or
uploaded there). Each is matched to an issue of a followed series by its
ComicInfo.xml or its name, written into the library as a tagged CBZ at
<Publisher>/<Series (Year)>/<Series> #<001> (<Year>).cbz, and removed from the
import folder. Files that match nothing stay put and are listed on the Import
page to be matched by hand.
"""

import logging
import os
from dataclasses import dataclass

from flask import current_app

from ..models import db
from . import archive, names, settings
from .models import DOWNLOADED, SKIPPED, ComicIssue, ComicSeries

logger = logging.getLogger(__name__)

# How alike a file's series name must be to a followed series' name.
SERIES_MATCH = 0.86


def comic_dir() -> str:
    return current_app.config["COMIC_DIR"]


def import_dir() -> str:
    return current_app.config.get("COMIC_IMPORT_DIR") or os.path.join(comic_dir(), "_import")


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
        pages = archive.write_cbz(src, tmp_dest, webp=opts["convert_webp"], quality=int(opts["webp_quality"]), metadata=lambda pages: (archive.comicinfo_xml(issue, series, pages, original), archive.metroninfo_xml(issue, series, pages, original)))
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
    return issue


def retag(issue: ComicIssue) -> None:
    """Rewrite an issue's embedded metadata after its details change."""
    if not issue.filename or not os.path.exists(abs_path(issue)):
        return
    archive.replace_metadata(abs_path(issue), archive.comicinfo_xml(issue, issue.series, issue.page_count or 0, issue.original_filename), archive.metroninfo_xml(issue, issue.series, issue.page_count or 0, issue.original_filename))


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


def comic_files(folder: str) -> list[str]:
    """Comic files under `folder`, oldest first; skips half-written ones."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if names.is_comic_file(name) and not name.endswith((".partial", ".new")):
                found.append(os.path.join(root, name))
    return sorted(found, key=lambda p: os.path.getmtime(p))


def scan_import_dir() -> dict:
    """Import every file in the import folder that matches an issue."""
    folder = import_dir()
    os.makedirs(folder, exist_ok=True)
    imported, unmatched, failed = [], [], []
    for path in comic_files(folder):
        match = match_file(path)
        if match.issue is None:
            unmatched.append(os.path.relpath(path, folder))
            continue
        try:
            import_file(path, match.issue)
            imported.append(match.issue.id)
        except archive.ArchiveError as e:
            logger.warning("Couldn't import %s: %s", path, e)
            failed.append(os.path.relpath(path, folder))
    return {"imported": imported, "unmatched": unmatched, "failed": failed}


def import_folder_path(rel: str) -> str:
    """A file in the import folder by its relative path; refuses anything outside it."""
    folder = os.path.realpath(import_dir())
    path = os.path.realpath(os.path.join(folder, rel))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        raise FileNotFoundError(rel)
    return path
