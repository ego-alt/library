"""Following series: adding them from a provider, and keeping their issues
up to date."""

from datetime import date, datetime, timedelta

from ..downloads.models import DOWNLOADED, SKIPPED, SNATCHED, WANTED
from ..models import _utcnow, db
from . import names
from .models import MONITOR_ALL, MONITOR_FUTURE, ComicIssue, ComicSeries
from .providers import get_provider

# Series are re-read from their provider this often (ongoing ones) or a tenth
# as often (no new issue for a year).
REFRESH_EVERY = timedelta(days=1)
REFRESH_ENDED_EVERY = timedelta(days=10)


def _apply_series(series: ComicSeries, data: dict) -> None:
    for key in ("name", "start_year", "publisher", "volume", "description", "issue_count", "cv_id", "metron_id"):
        if data.get(key) not in (None, ""):
            setattr(series, key, data[key])
    if data.get("cover_url"):
        series.cover_url = data["cover_url"]


def _status_for_new_issue(series: ComicSeries, issue: ComicIssue, first_sync: bool) -> str:
    """Whether an issue we've just learned about is wanted."""
    if issue.filename:
        return DOWNLOADED
    if series.monitor == MONITOR_ALL:
        return WANTED
    if series.monitor == MONITOR_FUTURE:
        released = issue.release_date
        if first_sync:
            # Only what isn't out yet when you add the series.
            return WANTED if released is None or released > date.today() else SKIPPED
        # A new issue showing up later is new, unless it's an old back issue
        # the provider just added.
        return WANTED if released is None or released >= (series.added_at.date() if series.added_at else date.today()) else SKIPPED
    return SKIPPED


def sync_issues(series: ComicSeries, rows: list[dict], first_sync: bool = False) -> int:
    """Merge the provider's issue list into the series. Returns how many issues are new."""
    by_provider_id = {i.provider_id: i for i in series.issues if i.provider_id}
    by_number = {names.normalize_number(i.number): i for i in series.issues}
    added = 0
    for row in rows:
        number = names.normalize_number(row["number"]) or "?"
        issue = by_provider_id.get(row["provider_id"])
        if issue is None:
            # An issue imported before the provider knew it, matched by number.
            issue = by_number.get(number)
            if issue is not None and issue.provider_id and issue.provider_id != row["provider_id"]:
                issue = None
        is_new = issue is None
        if is_new:
            issue = ComicIssue(series=series, number=number)
            db.session.add(issue)
            added += 1
        issue.provider_id = row["provider_id"]
        issue.number = number
        issue.sort_number = names.sort_number(number)
        for key in ("title", "cover_date", "store_date", "cover_url", "description"):
            if row.get(key) not in (None, ""):
                setattr(issue, key, row[key])
        if is_new:
            issue.status = _status_for_new_issue(series, issue, first_sync)
        by_provider_id[issue.provider_id] = issue
        by_number[number] = issue
    # Metron gives no series cover: use the first issue's.
    if not series.cover_url:
        first = min((i for i in series.issues if i.cover_url), key=lambda i: i.sort_number, default=None)
        if first:
            series.cover_url = first.cover_url
    series.refreshed_at = _utcnow()
    return added


def add_series(provider_name: str, provider_id: str, monitor: str = MONITOR_FUTURE, *, fetch_issues: bool = True) -> ComicSeries:
    """Follow a series. If it's already followed, that series is returned.
    Without fetch_issues only the series is read now; its issues come with
    the worker's next refresh (refreshed_at stays empty until then)."""
    existing = ComicSeries.query.filter_by(provider=provider_name, provider_id=str(provider_id)).first()
    if existing:
        return existing
    provider = get_provider(provider_name)
    data = provider.get_series(provider_id)
    series = ComicSeries(provider=provider_name, provider_id=str(provider_id), monitor=monitor, name=data["name"])
    _apply_series(series, data)
    db.session.add(series)
    if fetch_issues:
        sync_issues(series, provider.get_issues(provider_id), first_sync=True)
    db.session.commit()
    return series


def refresh_series(series: ComicSeries) -> int:
    """Re-read a series from its provider. Returns how many issues are new."""
    if series.provider not in ("comicvine", "metron"):
        return 0
    provider = get_provider(series.provider)
    first_sync = series.refreshed_at is None
    _apply_series(series, provider.get_series(series.provider_id))
    added = sync_issues(series, provider.get_issues(series.provider_id), first_sync=first_sync)
    db.session.commit()
    return added


def due_for_refresh(now: datetime | None = None) -> list[ComicSeries]:
    now = (now or _utcnow()).replace(tzinfo=None)
    due = []
    for series in ComicSeries.query.filter(ComicSeries.provider.in_(("comicvine", "metron"))).all():
        if series.refreshed_at is None:
            due.append(series)
            continue
        latest = max((i.release_date for i in series.issues if i.release_date), default=None)
        quiet = latest is not None and latest < now.date() - timedelta(days=365)
        if now - series.refreshed_at >= (REFRESH_ENDED_EVERY if quiet else REFRESH_EVERY):
            due.append(series)
    return due


def set_monitor(series: ComicSeries, monitor: str) -> int:
    """Change what's wanted. Turning to 'all' wants every missing issue; to
    'none' un-wants everything not already downloading. Returns how many
    issues are wanted now."""
    series.monitor = monitor
    for issue in series.issues:
        if issue.status in (DOWNLOADED, SNATCHED) or issue.filename:
            continue
        if monitor == MONITOR_ALL:
            issue.status = WANTED
        elif monitor == MONITOR_FUTURE:
            issue.status = WANTED if not issue.released else SKIPPED
        else:
            issue.status = SKIPPED
    db.session.commit()
    return sum(1 for i in series.issues if i.status == WANTED)


def local_series(name: str, year: int | None) -> ComicSeries:
    """A series made from files, for comics no provider knows (or before a key is set)."""
    key = f"{names.normalize_series(name)}|{year or ''}"[:32]
    series = ComicSeries.query.filter_by(provider="local", provider_id=key).first()
    if series is None:
        series = ComicSeries(provider="local", provider_id=key, name=name, start_year=year, monitor="none", refreshed_at=_utcnow())
        db.session.add(series)
        db.session.flush()
    return series
