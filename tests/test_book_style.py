"""The reader keeps a safe subset of each book's own styling (centred titles,
italics, small caps, relative sizes) and drops the rest."""

import io
import zipfile

from library.utils import book_style_subset
from tests._epub_builder import build_epub3

CSS = """
/* publisher styles */
body { font-family: "Times"; color: #000; }
.tx  { font-size: small; text-align: justify; text-indent: 1em; margin-top: .5em; }
.ct  { font-size: large; text-align: center; margin-bottom: 2em; }
.ep  { font-style: italic; text-align: center; font-family: Georgia; }
.sc  { font-variant: small-caps; letter-spacing: 0.1em; color: red; }
.poem { margin-left: 2em; padding-left: 9em; }
p.big { font-weight: bold; font-size: 300%; }
.a .b { text-align: center; }
@media print { .ct { text-align: left; } }
"""


def _epub(tmp_path, css=CSS):
    body = '<div class="ct">II</div>' + '<p class="tx">body</p>' * 5 + '<p class="ep">epigraph</p>'
    chapters = [("ch1.xhtml", body)]
    data = io.BytesIO(build_epub3(chapters=chapters))
    with zipfile.ZipFile(data, "a") as z:
        z.writestr("OEBPS/style.css", css)
    path = tmp_path / "book.epub"
    path.write_bytes(data.getvalue())
    return str(path)


def _rule(css, selector):
    prefix = f"#chapter-content {selector} {{"
    return next((line for line in css.splitlines() if line.startswith(prefix)), "")


def test_keeps_structure_scoped_to_the_reading_column(tmp_path):
    css = book_style_subset(_epub(tmp_path))
    assert "text-align: center" in _rule(css, ".ct")
    ep = _rule(css, ".ep")
    assert "font-style: italic" in ep and "text-align: center" in ep
    sc = _rule(css, ".sc")
    assert "font-variant-caps: small-caps" in sc and "letter-spacing: 0.1em" in sc
    assert "font-weight: 600" in _rule(css, "p.big")
    assert all(line.startswith("#chapter-content ") for line in css.splitlines())


def test_sizes_are_relative_to_the_books_body_text(tmp_path):
    css = book_style_subset(_epub(tmp_path))
    # Body text (.tx, the most-used class) is "small"; "large" is 1.2/0.89 of it.
    assert "font-size: 1.35em" in _rule(css, ".ct")
    assert "font-size" not in _rule(css, ".tx")  # body text stays the reader's size
    assert "font-size: 2.00em" in _rule(css, "p.big")  # 300% is clamped to 2×


def test_drops_what_the_reader_sets_for_comfort(tmp_path):
    css = book_style_subset(_epub(tmp_path))
    banned_words = ("justify", "text-indent", "margin-top", "margin-bottom", "font-family", "color", "Times")
    for banned in banned_words:
        assert banned not in css
    assert "body" not in css and ".a .b" not in css  # only simple class selectors
    assert "text-align: left" not in css  # @media blocks skipped
    poem = _rule(css, ".poem")
    # Indents are capped at 4em.
    assert "margin-left: 2em" in poem and "padding-left: 4em" in poem


def test_no_stylesheet_means_no_rules(tmp_path):
    path = tmp_path / "plain.epub"
    path.write_bytes(build_epub3())
    assert book_style_subset(str(path)) == ""


def test_reader_receives_the_subset(standard_client, book_dir):
    from library.models import Book, db

    (book_dir / "styled.epub").write_bytes(open(_epub(book_dir), "rb").read())
    db.session.add(Book(title="Styled", author="A", filename="styled.epub"))
    db.session.commit()
    stream = standard_client.get("/load_book/styled.epub").data.decode()
    first_line = stream.splitlines()[0]
    assert "#chapter-content .ep" in first_line
