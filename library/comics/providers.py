"""Comic metadata from ComicVine and Metron.

Both answer the same three questions, as plain dicts:
  search_series(query) -> [series]
  get_series(id) -> series
  get_issues(series_id) -> [issue]

series: {provider, provider_id, name, start_year, publisher, volume,
         description, cover_url, issue_count, cv_id, metron_id}
issue:  {provider_id, number, title, cover_date, store_date, cover_url, description}

ComicVine needs a free API key and allows about one request a second; Metron
needs a free account and allows 30 requests a minute. Both are throttled here.
"""

import re
import threading
import time
from datetime import date

import httpx
from bs4 import BeautifulSoup

from .. import settings
from ..config import USER_AGENT


class ProviderError(Exception):
    """The provider couldn't answer: no key, bad key, rate limit, or down."""


class _Throttle:
    """At most one request per `interval` seconds, across threads."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _year(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def plain_text(html: str | None) -> str:
    """ComicVine descriptions are HTML; keep the words."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class ComicVine:
    name = "comicvine"
    base_url = "https://comicvine.gamespot.com/api"
    throttle = _Throttle(1.1)

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ProviderError("Add a ComicVine API key in Settings.")
        self.api_key = api_key
        self.http = httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, transport=transport)

    def _get(self, path: str, **params) -> dict:
        self.throttle.wait()
        params.update(api_key=self.api_key, format="json")
        try:
            response = self.http.get(f"{self.base_url}/{path}", params=params)
        except httpx.HTTPError as e:
            raise ProviderError("ComicVine isn't answering right now. Try again in a moment.") from e
        if response.status_code in (401, 403):
            raise ProviderError("ComicVine refused the API key.")
        if response.status_code == 420 or response.status_code == 429:
            raise ProviderError("ComicVine's rate limit was hit; try again in a few minutes.")
        if response.status_code >= 400:
            raise ProviderError(f"ComicVine answered {response.status_code}.")
        data = response.json()
        # status_code 1 is OK; 100 is a bad key, 107 the rate limit.
        if data.get("status_code") != 1:
            raise ProviderError(f"ComicVine: {data.get('error', 'unknown error')}.")
        return data

    @staticmethod
    def _series(row: dict) -> dict:
        image = row.get("image") or {}
        return {
            "provider": "comicvine",
            "provider_id": str(row["id"]),
            "name": row.get("name") or "",
            "start_year": _year(row.get("start_year")),
            "publisher": (row.get("publisher") or {}).get("name"),
            "volume": None,
            "description": plain_text(row.get("description")) or (row.get("deck") or ""),
            "cover_url": image.get("medium_url") or image.get("original_url"),
            "issue_count": row.get("count_of_issues"),
            "cv_id": row["id"],
            "metron_id": None,
        }

    def search_series(self, query: str) -> list[dict]:
        fields = "id,name,start_year,publisher,count_of_issues,image,deck"
        data = self._get("search/", query=query, resources="volume", field_list=fields, limit=20)
        return [self._series(row) for row in data.get("results", [])]

    def get_series(self, provider_id: str) -> dict:
        fields = "id,name,start_year,publisher,count_of_issues,image,deck,description"
        data = self._get(f"volume/4050-{int(provider_id)}/", field_list=fields)
        return self._series(data["results"])

    def get_issues(self, provider_id: str) -> list[dict]:
        fields = "id,issue_number,name,cover_date,store_date,image,deck"
        issues, offset = [], 0
        while True:
            data = self._get("issues/", filter=f"volume:{int(provider_id)}", field_list=fields, sort="cover_date:asc", offset=offset, limit=100)
            for row in data.get("results", []):
                image = row.get("image") or {}
                issues.append({
                    "provider_id": str(row["id"]),
                    "number": str(row.get("issue_number") or "").strip(),
                    "title": row.get("name"),
                    "cover_date": _date(row.get("cover_date")),
                    "store_date": _date(row.get("store_date")),
                    "cover_url": image.get("medium_url") or image.get("original_url"),
                    "description": row.get("deck") or "",
                })
            offset += 100
            if offset >= data.get("number_of_total_results", 0):
                return issues


class Metron:
    name = "metron"
    base_url = "https://metron.cloud/api"
    throttle = _Throttle(2.1)

    def __init__(self, username: str, password: str, transport: httpx.BaseTransport | None = None):
        if not (username and password):
            raise ProviderError("Add your Metron username and password in Settings.")
        self.http = httpx.Client(timeout=20, auth=(username, password), headers={"User-Agent": USER_AGENT}, transport=transport)

    def _get(self, url: str, **params) -> dict:
        self.throttle.wait()
        if not url.startswith("http"):
            url = f"{self.base_url}/{url}"
        try:
            # An empty params would wipe the query of a "next page" URL.
            response = self.http.get(url, params=params or None)
        except httpx.HTTPError as e:
            raise ProviderError("Metron isn't answering right now. Try again in a moment.") from e
        if response.status_code in (401, 403):
            raise ProviderError("Metron refused the username or password.")
        if response.status_code == 429:
            raise ProviderError("Metron's rate limit was hit; try again in a minute.")
        if response.status_code >= 400:
            raise ProviderError(f"Metron answered {response.status_code}.")
        return response.json()

    def _pages(self, url: str, **params):
        data = self._get(url, **params)
        while True:
            yield from data.get("results", [])
            if not data.get("next"):
                return
            data = self._get(data["next"])

    def search_series(self, query: str) -> list[dict]:
        data = self._get("series/", name=query)
        results = []
        for row in data.get("results", [])[:20]:
            # The list gives "Batman (2016)" as `series`; details come with get_series.
            name = re.sub(r"\s*\(\d{4}\)\s*$", "", row.get("series") or "")
            results.append({
                "provider": "metron",
                "provider_id": str(row["id"]),
                "name": name,
                "start_year": row.get("year_began"),
                "publisher": None,
                "volume": row.get("volume"),
                "description": "",
                "cover_url": None,
                "issue_count": row.get("issue_count"),
                "cv_id": None,
                "metron_id": row["id"],
            })
        return results

    def get_series(self, provider_id: str) -> dict:
        row = self._get(f"series/{int(provider_id)}/")
        return {
            "provider": "metron",
            "provider_id": str(row["id"]),
            "name": row.get("name") or "",
            "start_year": row.get("year_began"),
            "publisher": (row.get("publisher") or {}).get("name"),
            "volume": row.get("volume"),
            "description": row.get("desc") or "",
            "cover_url": None,
            "issue_count": row.get("issue_count"),
            "cv_id": row.get("cv_id"),
            "metron_id": row["id"],
        }

    def get_issues(self, provider_id: str) -> list[dict]:
        return [
            {
                "provider_id": str(row["id"]),
                "number": str(row.get("number") or "").strip(),
                "title": None,
                "cover_date": _date(row.get("cover_date")),
                "store_date": _date(row.get("store_date")),
                "cover_url": row.get("image"),
                "description": "",
            }
            for row in self._pages("issue/", series_id=int(provider_id))
        ]


def available() -> list[str]:
    """Providers with credentials, ComicVine first."""
    names = []
    if settings.get("comicvine_api_key"):
        names.append("comicvine")
    if settings.get("metron_username") and settings.get("metron_password"):
        names.append("metron")
    return names


def get_provider(name: str | None = None):
    """The named provider, or the first one with credentials."""
    if name is None:
        names = available()
        if not names:
            raise ProviderError("Add a ComicVine API key or a Metron account in Settings to look up series.")
        name = names[0]
    if name == "comicvine":
        return ComicVine(settings.get("comicvine_api_key"))
    if name == "metron":
        return Metron(settings.get("metron_username"), settings.get("metron_password"))
    raise ProviderError(f"No metadata provider called {name!r}.")
