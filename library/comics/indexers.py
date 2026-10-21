"""Searching Newznab (usenet) and Torznab (torrent) indexers.

Both speak the same API: GET <url>/api?t=search&q=…&cat=7030 answers an RSS
feed whose items carry the release name, a link to the NZB or torrent, and
<newznab:attr>/<torznab:attr> extras (size, seeders). 7030 is the standard
Comics category; Prowlarr and Jackett expose Torznab feeds for torrent sites.
"""

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from .providers import USER_AGENT

COMICS_CATEGORY = "7030"
_ATTR_NAMESPACES = ("http://www.newznab.com/DTD/2010/feeds/attributes/", "http://torznab.com/schemas/2015/feed")


class IndexerError(Exception):
    pass


@dataclass
class Release:
    title: str
    url: str
    size: int | None
    indexer: str
    protocol: str  # usenet | torrent
    published: str | None = None
    seeders: int | None = None
    score: float = 0.0
    note: str = ""

    def public(self) -> dict:
        """For the browser: everything but the link, which can hold the indexer's key."""
        return {"title": self.title, "size": self.size, "indexer": self.indexer, "protocol": self.protocol, "published": self.published, "seeders": self.seeders, "score": round(self.score, 2), "note": self.note}


def _attrs(item: ET.Element) -> dict:
    attrs = {}
    for ns in _ATTR_NAMESPACES:
        for attr in item.findall(f"{{{ns}}}attr"):
            attrs[attr.get("name")] = attr.get("value")
    return attrs


def parse_feed(xml: bytes | str, indexer: str, protocol: str) -> list[Release]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise IndexerError(f"{indexer} answered something that isn't a feed.") from e
    if root.tag == "error":
        raise IndexerError(f"{indexer}: {root.get('description') or root.get('code')}")
    releases = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        enclosure = item.find("enclosure")
        url = (enclosure.get("url") if enclosure is not None else None) or item.findtext("link")
        if not title or not url:
            continue
        attrs = _attrs(item)
        size = attrs.get("size") or (enclosure.get("length") if enclosure is not None else None) or item.findtext("size")
        published = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(published).date().isoformat() if published else None
        except (TypeError, ValueError):
            published = None
        seeders = attrs.get("seeders")
        releases.append(Release(
            title=title,
            url=url.strip(),
            size=int(size) if size and str(size).isdigit() else None,
            indexer=indexer,
            protocol=protocol,
            published=published,
            seeders=int(seeders) if seeders and seeders.isdigit() else None,
        ))
    return releases


def search(indexer: dict, query: str, transport: httpx.BaseTransport | None = None) -> list[Release]:
    """Search one indexer config ({name, kind, url, api_key, categories})."""
    kind = indexer.get("kind", "newznab")
    protocol = "torrent" if kind == "torznab" else "usenet"
    base = indexer["url"].rstrip("/")
    # Prowlarr/Jackett give the full .../api URL; a plain Newznab host doesn't.
    url = base if base.endswith("/api") else f"{base}/api"
    params = {"t": "search", "q": query, "cat": indexer.get("categories") or COMICS_CATEGORY, "apikey": indexer.get("api_key", ""), "limit": 100}
    try:
        with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True, transport=transport) as http:
            response = http.get(url, params=params)
    except httpx.HTTPError as e:
        raise IndexerError(f"{indexer.get('name', base)} didn't answer ({e.__class__.__name__}).") from e
    if response.status_code in (401, 403):
        raise IndexerError(f"{indexer.get('name', base)} refused the API key.")
    if response.status_code >= 400:
        raise IndexerError(f"{indexer.get('name', base)} answered {response.status_code}.")
    return parse_feed(response.content, indexer.get("name", base), protocol)


def test(indexer: dict, transport: httpx.BaseTransport | None = None) -> str:
    """Check an indexer answers; returns a sentence for the settings page."""
    kind = indexer.get("kind", "newznab")
    base = indexer["url"].rstrip("/")
    url = base if base.endswith("/api") else f"{base}/api"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True, transport=transport) as http:
            response = http.get(url, params={"t": "caps", "apikey": indexer.get("api_key", "")})
    except httpx.HTTPError as e:
        raise IndexerError(f"Didn't answer ({e.__class__.__name__}).") from e
    if response.status_code >= 400:
        raise IndexerError(f"Answered {response.status_code}.")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        raise IndexerError("That isn't a Newznab or Torznab API.") from e
    if root.tag == "error":
        raise IndexerError(root.get("description") or "It refused.")
    comics = any(c.get("id") == COMICS_CATEGORY for c in root.iter("subcat")) or any(c.get("id") == COMICS_CATEGORY for c in root.iter("category"))
    return f"Connected to a {'Torznab' if kind == 'torznab' else 'Newznab'} indexer" + ("" if comics else " (it doesn't list Comics, 7030: set the category it files comics under)") + "."
