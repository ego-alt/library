import os

import pytest

from library.utils import (
    cover_mimetype,
    extract_metadata,
    get_epub_structure,
    process_chapter_content,
    read_epub_cover,
    rotate_list,
    update_epub_cover,
)
from tests._epub_builder import (
    build_epub2_ncx,
    build_epub3,
    build_epub_no_toc,
)


@pytest.fixture
def epub_path(tmp_path):
    """Write a synthesized EPUB to disk and return its path."""

    def _write(data: bytes, name: str = "book.epub") -> str:
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)

    return _write


# --- rotate_list ----------------------------------------------------------------


def test_rotate_list_zero_is_noop():
    assert rotate_list([1, 2, 3], 0) == [1, 2, 3]


def test_rotate_list_negative_shifts_left():
    # n=-1 starts the list at index 1
    assert rotate_list([1, 2, 3, 4], -1) == [2, 3, 4, 1]


# --- cover_mimetype -------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("foo.png", "image/png"),
        ("foo.PNG", "image/png"),
        ("foo.jpg", "image/jpeg"),
        ("foo.jpeg", "image/jpeg"),
        ("foo.svg", "image/svg+xml"),
        ("foo.unknown", "image/jpeg"),  # default
        ("", "image/jpeg"),
    ],
)
def test_cover_mimetype(path, expected):
    assert cover_mimetype(path) == expected


# --- get_epub_structure ---------------------------------------------------------


def test_structure_epub3_uses_nav_doc(epub_path):
    path = epub_path(
        build_epub3(
            chapters=[("ch1.xhtml", "<h1>One</h1>"), ("ch2.xhtml", "<h1>Two</h1>")],
            nav_entries=[
                {
                    "title": "Part One",
                    "href": "ch1.xhtml",
                    "children": [
                        {"title": "Section A", "href": "ch1.xhtml#a", "children": []}
                    ],
                },
                {"title": "Part Two", "href": "ch2.xhtml", "children": []},
            ],
        )
    )

    s = get_epub_structure(path)

    assert s["spine_length"] == 3  # nav + 2 chapters
    assert len(s["toc"]) == 2
    assert s["toc"][0]["title"] == "Part One"
    assert s["toc"][0]["spine_index"] == 1  # nav is index 0
    assert s["toc"][0]["children"][0]["section_id"] == "a"
    assert s["toc"][1]["title"] == "Part Two"
    assert s["toc"][1]["spine_index"] == 2


def test_structure_epub2_falls_back_to_ncx(epub_path):
    path = epub_path(
        build_epub2_ncx(
            chapters=[("ch1.xhtml", "<h1>A</h1>"), ("ch2.xhtml", "<h1>B</h1>")],
            nav_entries=[
                {
                    "title": "Foreword",
                    "href": "ch1.xhtml",
                    "children": [
                        {"title": "About", "href": "ch1.xhtml#about", "children": []}
                    ],
                },
                {"title": "Chapter 1", "href": "ch2.xhtml", "children": []},
            ],
        )
    )

    s = get_epub_structure(path)

    assert s["spine_length"] == 2
    assert s["toc"][0]["title"] == "Foreword"
    assert s["toc"][0]["children"][0]["section_id"] == "about"
    assert s["toc"][1]["title"] == "Chapter 1"


def test_structure_no_usable_toc_falls_back_to_synthetic(epub_path):
    path = epub_path(build_epub_no_toc())
    s = get_epub_structure(path)

    assert s["spine_length"] == 2
    assert len(s["toc"]) == 2
    assert all(e["synthetic"] is True for e in s["toc"])
    assert s["toc"][0]["title"] == "Section 1"
    assert s["toc"][0]["spine_index"] == 0


def test_structure_lists_images_with_paths(epub_path):
    path = epub_path(build_epub3())
    s = get_epub_structure(path)
    assert s["image_count"] >= 1
    # The cover.png we put at OEBPS/cover.png should be discoverable
    cover_entry = next(
        (v for k, v in s["images"].items() if k.endswith("cover.png")), None
    )
    assert cover_entry is not None
    assert cover_entry["media-type"] == "image/png"


# --- read_epub_cover ------------------------------------------------------------


def test_read_epub_cover_returns_bytes(epub_path):
    path = epub_path(build_epub3())
    data = read_epub_cover(path, "OEBPS/cover.png")
    assert isinstance(data, bytes)
    assert data.startswith(b"\x89PNG")


def test_read_epub_cover_autodetects_path_when_omitted(epub_path):
    path = epub_path(build_epub3())
    # cover_path=None → looks up via the OPF metadata
    data = read_epub_cover(path)
    assert data.startswith(b"\x89PNG")


# --- update_epub_cover ----------------------------------------------------------


def test_update_epub_cover_replaces_bytes(epub_path):
    path = epub_path(build_epub3())
    new_bytes = b"\x89PNG\r\n\x1a\nNEW-COVER-MARKER"
    update_epub_cover(path, new_bytes)

    # Re-reading must return the new bytes
    assert read_epub_cover(path, "OEBPS/cover.png") == new_bytes


# --- extract_metadata -----------------------------------------------------------


def test_extract_metadata_pulls_title_and_author(epub_path):
    from ebooklib import epub as _epub

    path = epub_path(build_epub3(title="Demo", author="Tester"))
    meta = extract_metadata(_epub.read_epub(path))
    assert meta == {"title": "Demo", "author": "Tester"}


# --- process_chapter_content ----------------------------------------------------


def test_process_chapter_rewrites_image_to_asset_url(epub_path):
    chapters = [
        ("ch1.xhtml", '<p>before</p><img src="cover.png"/><p>after</p>'),
    ]
    path = epub_path(build_epub3(chapters=chapters))
    s = get_epub_structure(path)
    chapter_path = next(c["path"] for c in s["chapters"] if c["path"].endswith("ch1.xhtml"))

    result = process_chapter_content(
        path, chapter_path, s["images"], asset_url_prefix="/book_asset/x.epub/"
    )
    assert "data:image/png;base64" not in result["content"]
    assert "/book_asset/x.epub/OEBPS/cover.png" in result["content"]
    assert 'loading="lazy"' in result["content"]


def test_process_chapter_extracts_h1_title(epub_path):
    chapters = [("ch1.xhtml", "<h1>Real Chapter Title</h1><p>body</p>")]
    path = epub_path(build_epub3(chapters=chapters))
    s = get_epub_structure(path)
    chapter_path = next(c["path"] for c in s["chapters"] if c["path"].endswith("ch1.xhtml"))

    result = process_chapter_content(path, chapter_path, s["images"], "/x/")
    assert result["title"] == "Real Chapter Title"


def test_process_chapter_rewrites_internal_links(epub_path):
    chapters = [
        ("ch1.xhtml", '<a href="ch2.xhtml#scene">go</a>'),
        ("ch2.xhtml", "<h1>Two</h1>"),
    ]
    path = epub_path(build_epub3(chapters=chapters))
    s = get_epub_structure(path)
    chapter_path = next(c["path"] for c in s["chapters"] if c["path"].endswith("ch1.xhtml"))

    result = process_chapter_content(path, chapter_path, s["images"], "/x/")
    # The href becomes a no-op JS hook; original target moves to data attributes
    assert "javascript:void" in result["content"]
    assert "ch2.xhtml" in result["content"]
    assert "scene" in result["content"]
