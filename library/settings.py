"""Shelves settings, kept in the database so they can be changed from the
Settings page: where to search and download (shared by books and comics),
and how comics are looked up and written.

Metadata keys can also come from the environment (COMICVINE_API_KEY,
METRON_USERNAME, METRON_PASSWORD); a value saved in the app wins.
"""

import copy
import json
import os

from .models import Setting, db

DEFAULTS = {
    "comicvine_api_key": "",
    "metron_username": "",
    "metron_password": "",
    # Newznab (usenet) and Torznab (torrent) indexers, for books and comics:
    # {"name", "kind": "newznab"|"torznab", "url", "api_key", "enabled",
    #  "categories" (comics, 7030 on most), "book_categories" (ebooks, 7020)}
    "indexers": [],
    # Where grabs go. Usenet results go to SABnzbd, torrents to qBittorrent;
    # with neither, a blackhole folder that some other client watches. Each
    # client files comics and books under their own category.
    "sabnzbd": {"url": "", "api_key": "", "category": "comics", "book_category": "books"},
    "qbittorrent": {"url": "", "username": "", "password": "", "category": "comics", "book_category": "books"},
    "blackhole_dir": "",
    # The client sees its download folder at remote_path; this app sees the
    # same folder at local_path.
    "path_map": {"remote_path": "", "local_path": ""},
    # Releases: preferred words raise a release's score, rejected ones rule it out.
    "preferred_words": ["digital"],
    "rejected_words": ["c2c scan", "webrip-preview"],
    "max_size_mb": 600,
    # How new files are written.
    "convert_webp": True,
    "webp_quality": 82,
    "rename": True,
    "search_interval_hours": 6,
}

# Values never sent back to the browser as they are.
SECRETS = ("comicvine_api_key", "metron_password")
_ENV = {
    "comicvine_api_key": "COMICVINE_API_KEY",
    "metron_username": "METRON_USERNAME",
    "metron_password": "METRON_PASSWORD",
}


def get(key: str):
    row = db.session.get(Setting, key)
    if row is not None:
        value = row.data
        if value not in ("", None):
            return value
    if key in _ENV and os.environ.get(_ENV[key]):
        return os.environ[_ENV[key]]
    return copy.deepcopy(DEFAULTS[key])


def get_all() -> dict:
    return {key: get(key) for key in DEFAULTS}


def set_many(values: dict) -> None:
    """Save the known keys in `values`; unknown keys are ignored."""
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = db.session.get(Setting, key)
        encoded = json.dumps(value)
        if row is None:
            db.session.add(Setting(key=key, value=encoded))
        else:
            row.value = encoded
    db.session.commit()


def masked(secret: str) -> str:
    """What the settings page shows for a saved secret."""
    return "•" * 8 + secret[-4:] if len(secret) > 8 else ("•" * 8 if secret else "")


def for_browser() -> dict:
    """All settings, with keys and passwords masked."""
    values = get_all()
    for key in SECRETS:
        values[key] = masked(values[key])
    for indexer in values["indexers"]:
        indexer["api_key"] = masked(indexer.get("api_key", ""))
    values["sabnzbd"]["api_key"] = masked(values["sabnzbd"].get("api_key", ""))
    values["qbittorrent"]["password"] = masked(values["qbittorrent"].get("password", ""))
    return values


def is_masked(value) -> bool:
    return isinstance(value, str) and value.startswith("••••")
