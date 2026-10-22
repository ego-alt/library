"""Finding books to ask for on Open Library (openlibrary.org/dev/docs/api/search).
No key needed; covers come from covers.openlibrary.org."""

import httpx

from ..config import USER_AGENT

SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL = "https://covers.openlibrary.org/b/id/{}-M.jpg"


class OpenLibraryError(Exception):
    pass


def search(query: str, limit: int = 20, transport: httpx.BaseTransport | None = None) -> list[dict]:
    """Works matching a title or author: [{ol_key, title, author, year, cover_url}]."""
    params = {"q": query, "limit": limit, "fields": "key,title,author_name,first_publish_year,cover_i"}
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, transport=transport) as http:
            response = http.get(SEARCH_URL, params=params)
    except httpx.HTTPError as e:
        raise OpenLibraryError("Open Library isn't answering right now. Try again in a moment.") from e
    if response.status_code >= 400:
        raise OpenLibraryError(f"Open Library answered {response.status_code}.")
    results = []
    for doc in response.json().get("docs", []):
        if not doc.get("key") or not doc.get("title"):
            continue
        authors = doc.get("author_name") or []
        results.append({
            "ol_key": doc["key"],
            "title": doc["title"],
            "author": ", ".join(authors[:2]) if authors else None,
            "year": doc.get("first_publish_year"),
            "cover_url": COVER_URL.format(doc["cover_i"]) if doc.get("cover_i") else None,
        })
    return results
