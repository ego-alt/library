"""Read aloud picks a voice by language, so the reader is told the book's
language (dc:language) and each chapter's own (lang on <html> or <body>)."""

import io
import json
import zipfile

from library.models import Book, db
from library.utils import get_epub_structure, process_chapter_content
from tests._epub_builder import build_epub3


def _epub(path, language="zh-HK", chapter_lang="en"):
    """A book in `language` whose second chapter says it's in `chapter_lang`."""
    source = zipfile.ZipFile(
        io.BytesIO(
            build_epub3(
                chapters=[("ch1.xhtml", "<p>今朝落咗場大雨。</p>"), ("ch2.xhtml", "<p>An English chapter.</p>")]
            )
        )
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.endswith(".opf") and language:
                data = data.replace(b"</dc:title>", f"</dc:title><dc:language>{language}</dc:language>".encode(), 1)
            if item.filename.endswith("ch2.xhtml"):
                data = data.replace(b"<html ", f'<html xml:lang="{chapter_lang}" '.encode(), 1)
            z.writestr(item, data)
    path.write_bytes(out.getvalue())
    return str(path)


def test_the_books_language(tmp_path):
    assert get_epub_structure(_epub(tmp_path / "a.epub"))["language"] == "zh-HK"
    assert get_epub_structure(_epub(tmp_path / "b.epub", language=None))["language"] == ""


def test_a_chapters_own_language(tmp_path):
    path = _epub(tmp_path / "a.epub")
    structure = get_epub_structure(path)
    langs = [
        process_chapter_content(path, c["path"], structure["images"], "/a/")["lang"] for c in structure["chapters"]
    ]
    assert langs[-1] == "en" and langs[-2] == ""


def test_the_reader_is_told(standard_client, book_dir):
    _epub(book_dir / "yue.epub")
    db.session.add(Book(title="Yue", author="A", filename="yue.epub"))
    db.session.commit()
    lines = [json.loads(line) for line in standard_client.get("/load_book/yue.epub").data.decode().splitlines()]
    assert lines[0]["language"] == "zh-HK"
    assert {c["lang"] for c in lines[1:] if c["type"] == "chapter"} >= {"en"}
