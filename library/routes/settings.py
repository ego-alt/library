"""Settings, for admins (the Settings card at the foot of Downloads): where
to search and download (shared by books and comics), and how comics are
looked up and written. This is their JSON API."""

from flask import Blueprint, jsonify, request

from .. import settings
from ..comics import providers
from ..downloads import clients, indexers
from ._helpers import json_admin_required

settings_blueprint = Blueprint("settings", __name__)

def _merge_secret(new, old):
    return old if settings.is_masked(new) else new


@settings_blueprint.get("/api/settings")
@json_admin_required
def get_settings():
    return jsonify(settings.for_browser())


@settings_blueprint.put("/api/settings")
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
                "book_categories": (indexer.get("book_categories") or indexers.BOOKS_CATEGORY).strip(),
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


@settings_blueprint.post("/api/settings/test")
@json_admin_required
def test_settings():
    """Try a provider, indexer or client with the values on the form, saved
    or not. Masked secrets ("••••1234") stand for the saved ones."""
    data = request.get_json(silent=True) or {}
    what, values = data.get("what"), data.get("values") or {}
    current = settings.get_all()
    try:
        if what == "comicvine":
            providers.ComicVine(_merge_secret(values.get("comicvine_api_key", ""), current["comicvine_api_key"])).search_series("batman")
            message = "ComicVine answered."
        elif what == "metron":
            providers.Metron(values.get("metron_username", ""), _merge_secret(values.get("metron_password", ""), current["metron_password"])).search_series("batman")
            message = "Metron answered."
        elif what == "indexer":
            saved = {(i.get("name"), i.get("url")): i for i in current["indexers"]}
            indexer = {"categories": indexers.COMICS_CATEGORY, **values}
            indexer["api_key"] = _merge_secret(values.get("api_key", ""), saved.get((values.get("name"), values.get("url")), {}).get("api_key", ""))
            message = indexers.test(indexer)
        elif what == "sabnzbd":
            message = clients.SABnzbd({**values, "api_key": _merge_secret(values.get("api_key", ""), current["sabnzbd"].get("api_key", ""))}).test()
        elif what == "qbittorrent":
            message = clients.QBittorrent({**values, "password": _merge_secret(values.get("password", ""), current["qbittorrent"].get("password", ""))}).test()
        elif what == "blackhole":
            message = clients.Blackhole(values.get("blackhole_dir", "")).test()
        else:
            return jsonify({"error": "Nothing to test here."}), 400
    except (providers.ProviderError, indexers.IndexerError, clients.ClientError) as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"message": message})
