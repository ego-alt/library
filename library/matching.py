"""Fuzzy title+author matching for the book-scanner lookup endpoint.

Given a scanned title/author, score each library book and surface the close
matches so the app can tell whether you already own the book. Scoring is
order-insensitive token similarity (stdlib :mod:`difflib`), so edition and
formatting differences still rank as the same book:

* "Harry Potter and the Sorcerer's Stone" ≈ "...Philosopher's Stone"
* "J.K. Rowling" ≈ "Rowling, J. K."

Title carries most of the weight; author only nudges the score when both sides
have one, since scan metadata frequently omits or mangles the author.
"""

import re
from difflib import SequenceMatcher

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Default similarity cutoff (0–1) for treating a library book as the scanned
# one. Overridable per-deployment via the LIBRARY_MATCH_THRESHOLD config/env var.
DEFAULT_MATCH_THRESHOLD = 0.6

_TITLE_WEIGHT = 0.7
_AUTHOR_WEIGHT = 0.3


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


def _token_set_ratio(a, b):
    """SequenceMatcher ratio over sorted, de-duplicated tokens, so word order
    and punctuation don't matter ("Rowling, J. K." == "J. K. Rowling")."""
    ta = " ".join(sorted(set(_tokens(a))))
    tb = " ".join(sorted(set(_tokens(b))))
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def score_book(query_title, query_author, book_title, book_author):
    """Similarity in [0, 1] between a scanned book and a library book."""
    title = _token_set_ratio(query_title, book_title)
    # Only let the author move the score when both sides actually have one.
    if _tokens(query_author) and _tokens(book_author):
        author = _token_set_ratio(query_author, book_author)
        return _TITLE_WEIGHT * title + _AUTHOR_WEIGHT * author
    return title


def rank_matches(query_title, query_author, books, threshold, limit=5):
    """Return ``[(book, score), ...]`` at or above ``threshold``, best first.

    ``books`` is any iterable of objects exposing ``.title`` and ``.author``.
    Capped to ``limit`` so a loose threshold can't return the whole library.
    """
    scored = [
        (book, score_book(query_title, query_author, book.title, book.author))
        for book in books
    ]
    scored = [pair for pair in scored if pair[1] >= threshold]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
