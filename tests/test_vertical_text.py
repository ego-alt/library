"""The reader is told when a book asks for vertical text: right-to-left page
turns in its spine, or writing-mode: vertical-rl in its CSS."""

import io
import json
import zipfile

from library.models import Book, db
from library.utils import get_epub_structure
from tests._epub_builder import build_epub3


def _epub(path, spine_rtl=False, css=None):
    source = zipfile.ZipFile(io.BytesIO(build_epub3(chapters=[("ch1.xhtml", "<p>我家門前有兩株樹。</p>")])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.endswith(".opf") and spine_rtl:
                data = data.replace(b"<spine", b'<spine page-progression-direction="rtl"', 1)
            z.writestr(item, data)
        if css is not None:
            z.writestr("OEBPS/style.css", css)
    path.write_bytes(out.getvalue())
    return str(path)


def test_a_book_asks_for_vertical_text(tmp_path):
    assert get_epub_structure(_epub(tmp_path / "rtl.epub", spine_rtl=True))["vertical"]
    assert get_epub_structure(_epub(tmp_path / "css.epub", css="body { -webkit-writing-mode: vertical-rl; }"))[
        "vertical"
    ]
    assert get_epub_structure(_epub(tmp_path / "old.epub", css="html { writing-mode:tb-rl }"))["vertical"]


def test_a_horizontal_book_does_not(tmp_path):
    assert not get_epub_structure(_epub(tmp_path / "plain.epub"))["vertical"]
    assert not get_epub_structure(_epub(tmp_path / "ltr.epub", css="p { writing-mode: horizontal-tb; }"))["vertical"]


def test_the_reader_is_told(standard_client, book_dir):
    _epub(book_dir / "v.epub", spine_rtl=True)
    db.session.add(Book(title="V", author="A", filename="v.epub"))
    db.session.commit()
    first = json.loads(standard_client.get("/load_book/v.epub").data.decode().splitlines()[0])
    assert first["type"] == "metadata" and first["vertical"] is True
