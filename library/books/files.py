"""Putting an EPUB into the library: a unique file name in BOOK_DIR, a Book
row, and its cover found inside the file. Used by uploads, downloads and the
import folder."""

import os
import re
import shutil

from ebooklib import epub
from flask import current_app

from ..models import Book, db
from ..utils import extract_metadata, get_epub_cover_path, get_epub_structure


class NotABook(Exception):
    pass


def _slugify(value: str) -> str:
    value = re.sub(r"[.,'\"]", "", value)
    value = re.sub(r"\s+", "_", value)
    # Strip anything that's not a safe filename char.
    value = re.sub(r"[^A-Za-z0-9_\-]", "", value)
    return value or "untitled"


def generate_filename(title: str, author: str, book_dir: str) -> str:
    """Build a unique <title>__<author>.epub filename, avoiding collisions on disk."""
    base = f"{_slugify(title)}__{_slugify(author)}"
    candidate = f"{base}.epub"
    i = 2
    while os.path.exists(os.path.join(book_dir, candidate)):
        candidate = f"{base}_{i}.epub"
        i += 1
    return candidate


def has_toc(path: str, epub_book=None) -> bool:
    """EPUB 3 books carry a nav document, EPUB 2 an NCX; the reader needs one."""
    if epub_book is not None and epub_book.get_items_of_type(epub.EpubNav):
        return True
    try:
        return bool(get_epub_structure(path)["toc"])
    except Exception:
        return False


def read_epub(path: str) -> dict:
    """Title, author and cover path from an EPUB; NotABook if the reader can't
    open it."""
    try:
        epub_book = epub.read_epub(path, options={"ignore_ncx": True})
    except Exception as e:
        raise NotABook("It isn't a readable EPUB.") from e
    if not has_toc(path, epub_book):
        raise NotABook("It has no table of contents, so the reader can't open it.")
    metadata = extract_metadata(epub_book) or {}
    try:
        cover_path = get_epub_cover_path(path)
    except Exception:
        cover_path = None
    return {"title": metadata.get("title"), "author": metadata.get("author"), "cover_path": cover_path}


def add_epub(src: str, *, title: str | None = None, author: str | None = None, uploaded_by: int | None = None, keep_source: bool = False) -> Book:
    """Copy (keep_source) or move an EPUB into the library and add its row.
    The title and author default to the file's own."""
    found = read_epub(src)
    title = (title or found["title"] or "Untitled").strip()[:200]
    author = (author or found["author"] or "Unknown author").strip()[:200]
    book_dir = current_app.config["BOOK_DIR"]
    os.makedirs(book_dir, exist_ok=True)
    filename = generate_filename(title, author, book_dir)
    dest = os.path.join(book_dir, filename)
    if keep_source:
        shutil.copy2(src, dest)
    else:
        shutil.move(src, dest)
    book = Book(title=title, author=author, filename=filename, cover_path=found["cover_path"], access_level="standard", uploaded_by=uploaded_by)
    db.session.add(book)
    db.session.commit()
    return book
