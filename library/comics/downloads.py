"""Comics in the shared download pipeline (downloads/pipeline.py): which
issues are wanted, what to search for, how a release is judged, and how a
finished download's files become issues."""

import logging

from flask import url_for

from ..downloads import indexers, pipeline
from ..downloads.models import KIND_COMIC, WANTED, Download
from . import files, names
from .models import ComicIssue, ComicSeries

logger = logging.getLogger(__name__)


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


def wanted_issues() -> list[ComicIssue]:
    """Wanted issues that are out, newest first."""
    issues = ComicIssue.query.filter_by(status=WANTED).all()
    return sorted((i for i in issues if i.released), key=lambda i: i.release_date or i.added_at.date(), reverse=True)


class ComicKind:
    name = KIND_COMIC
    fk = "issue_id"

    def wanted(self) -> list[ComicIssue]:
        return wanted_issues()

    def queries(self, issue: ComicIssue) -> list[str]:
        """The series by name (one search covers many issues), then the
        series and the zero-padded number."""
        name = _query_name(issue.series)
        number = names.normalize_number(issue.number) or ""
        return [name, f"{name} {number.zfill(3) if number.isdigit() else number}"]

    def score(self, release, issue, opts, blocked):
        return score_release(release, issue, opts, blocked)

    def import_files(self, download: Download, paths: list[str], keep: bool) -> None:
        found = [f for f in paths if names.is_comic_file(f)]
        if not found:
            raise pipeline.ImportFilesError("The download has no comic file in it.")
        target = download.issue
        if len(found) == 1 and target is not None:
            files.import_file(found[0], target, remove_source=not keep)
        else:
            for file in found:
                match = files.match_file(file)
                if match.issue:
                    files.import_file(file, match.issue, remove_source=not keep)
        if target is not None and not target.filename:
            raise pipeline.ImportFilesError("None of its files matched the issue.")

    def label(self, issue: ComicIssue) -> str:
        return f"{issue.series.display_name} #{issue.number}"

    def link(self, issue: ComicIssue) -> str:
        return url_for("comics.series_page", series_id=issue.series_id)


kind = ComicKind()


# Shorthands for comics code and tests.
def find_releases(issue: ComicIssue, cache: dict | None = None):
    return pipeline.find_releases(KIND_COMIC, issue, cache)


def grab(issue: ComicIssue, release: indexers.Release) -> Download:
    return pipeline.grab(KIND_COMIC, issue, release)


def search_issue(issue: ComicIssue, cache: dict | None = None, *, raise_client_errors: bool = False) -> Download | None:
    return pipeline.search_item(KIND_COMIC, issue, cache, raise_client_errors=raise_client_errors)


def mark_imported(issue_ids: list[int]) -> None:
    pipeline.mark_imported(KIND_COMIC, issue_ids)
