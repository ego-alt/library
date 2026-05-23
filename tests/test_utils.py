import pytest

from library.utils import (
    cover_mimetype,
    extract_metadata,
    get_epub_cover_path,
    get_epub_structure,
    process_chapter_content,
    read_epub_cover,
    rotate_list,
    update_epub_cover,
)
from tests._epub_builder import (
    build_epub2_ncx,
    build_epub3,
    build_epub3_xhtml_cover_wrapper,
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


# --- In-content "Contents" page detection -------------------------------------


def test_structure_uses_in_content_contents_page_when_ncx_is_broken(epub_path):
    """When the NCX points at a missing file, fall through to a real
    'Contents' page in the spine and use its <a href> links."""
    contents_html = """
        <h1>Contents</h1>
        <p><a href="ch1.xhtml">Foreword</a></p>
        <p><a href="ch2.xhtml">Chapter 1: The Beginning</a></p>
        <p><a href="ch3.xhtml">Chapter 2: Middles</a></p>
    """
    path = epub_path(build_epub2_ncx(
        chapters=[
            ("toc.xhtml", contents_html),
            ("ch1.xhtml", "<h1>Foreword</h1><p>body</p>" * 20),
            ("ch2.xhtml", "<h1>Chapter 1</h1><p>body</p>" * 20),
            ("ch3.xhtml", "<h1>Chapter 2</h1><p>body</p>" * 20),
        ],
        # NCX points at a non-existent file → resolved TOC is empty → falls through
        nav_entries=[{"title": "Start", "href": "doesnotexist.xhtml", "children": []}],
    ))

    s = get_epub_structure(path)
    titles = [e["title"] for e in s["toc"]]
    assert titles == ["Foreword", "Chapter 1: The Beginning", "Chapter 2: Middles"]
    # Spine indices should resolve correctly (toc.xhtml = 0, ch1=1, ch2=2, ch3=3)
    assert [e["spine_index"] for e in s["toc"]] == [1, 2, 3]
    # Not synthetic
    assert all("synthetic" not in e or not e["synthetic"] for e in s["toc"])


def test_contents_page_with_too_few_links_does_not_trigger(epub_path):
    """A contents page with fewer than 3 spine-resolving links should not
    be trusted — fall through to synthetic."""
    contents_html = """
        <h1>Contents</h1>
        <p><a href="ch1.xhtml">Only One Link</a></p>
    """
    path = epub_path(build_epub2_ncx(
        chapters=[
            ("toc.xhtml", contents_html),
            ("ch1.xhtml", "<h1>One</h1><p>body</p>" * 20),
            ("ch2.xhtml", "<h1>Two</h1><p>body</p>" * 20),
        ],
        nav_entries=[{"title": "Missing", "href": "doesnotexist.xhtml", "children": []}],
    ))

    s = get_epub_structure(path)
    # Synthetic fallback kicked in
    assert all(e.get("synthetic") for e in s["toc"])


def test_contents_page_recognised_via_inline_span_marker(epub_path):
    """Real-world EPUBs (e.g. Calibre output) often use a styled <span> rather
    than an <h1> for the 'CONTENTS' label. The detector must catch that."""
    contents_html = """
        <p><span class="sgc2">CONTENTS</span></p>
        <p><a href="ch1.xhtml">PART ONE</a></p>
        <p><a href="ch2.xhtml">PART TWO</a></p>
        <p><a href="ch3.xhtml">PART THREE</a></p>
    """
    path = epub_path(build_epub2_ncx(
        chapters=[
            ("toc.xhtml", contents_html),
            ("ch1.xhtml", "<p>body</p>" * 30),
            ("ch2.xhtml", "<p>body</p>" * 30),
            ("ch3.xhtml", "<p>body</p>" * 30),
        ],
        nav_entries=[{"title": "Missing", "href": "nope.xhtml", "children": []}],
    ))
    s = get_epub_structure(path)
    titles = [e["title"] for e in s["toc"]]
    assert titles == ["PART ONE", "PART TWO", "PART THREE"]


def test_real_chapter_mentioning_contents_does_not_false_match(epub_path):
    """A regular chapter that happens to use the word 'Contents' in its
    heading must not be mistaken for a TOC page (low link-resolution ratio)."""
    chapter_with_contents = """
        <h1>Contents of the Cabinet</h1>
        <p>Then the inspector turned to the cabinet's contents and...</p>
        <p>Read more at <a href="https://example.com/footnote-1">our website</a></p>
        <p>Or see <a href="mailto:reviewer@example.com">the reviewer</a></p>
        <p>Chapter cross-ref: <a href="ch3.xhtml">somewhere</a></p>
    """
    path = epub_path(build_epub2_ncx(
        chapters=[
            ("ch1.xhtml", chapter_with_contents),
            ("ch2.xhtml", "<h1>Chapter 2</h1><p>body</p>" * 20),
            ("ch3.xhtml", "<h1>Chapter 3</h1><p>body</p>" * 20),
        ],
        nav_entries=[{"title": "Missing", "href": "doesnotexist.xhtml", "children": []}],
    ))

    s = get_epub_structure(path)
    # Should NOT have used the chapter as a contents page (only 1/3 links resolve)
    # → synthetic fallback
    assert all(e.get("synthetic") for e in s["toc"])


# --- get_chapter_title heuristic improvements ---------------------------------


def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")


def test_chapter_title_prefers_h1_over_h2_even_if_h2_appears_first():
    from library.utils import get_chapter_title
    html = "<h2>Subsection</h2><h1>The Real Title</h1>"
    assert get_chapter_title(None, _soup(html)) == "The Real Title"


def test_chapter_title_normalizes_whitespace():
    from library.utils import get_chapter_title
    html = "<h1>\n  The   Title  \n</h1>"
    assert get_chapter_title(None, _soup(html)) == "The Title"


def test_chapter_title_falls_back_to_head_title_when_no_headings():
    from bs4 import BeautifulSoup

    from library.utils import get_chapter_title
    html = "<html><head><title>Chapter from head</title></head><body><p>body text</p></body></html>"
    assert get_chapter_title(None, BeautifulSoup(html, "html.parser")) == "Chapter from head"


def test_chapter_title_loosened_short_paragraph_threshold():
    from library.utils import get_chapter_title
    # 50-char paragraph: previously rejected (limit was 25), now accepted
    html = "<p>A medium-length opening paragraph that fits in 50.</p>"
    title = get_chapter_title(None, _soup(html))
    assert title and title.startswith("A medium-length")


def test_chapter_title_skips_headings_inside_nav():
    from library.utils import get_chapter_title
    # Contents page with the only heading inside <nav> should not return "Contents"
    html = '<nav><h1>Contents</h1></nav><p>some content paragraph here</p>'
    title = get_chapter_title(None, _soup(html))
    assert title != "Contents"


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


def test_normalize_internal_epub_path_percent_decodes():
    from library.utils import _normalize_internal_epub_path

    raw = "OEBPS/Images/Nabokov%2C%20Vladimir%20-%20Defense%20%28Vintage%2C%201990%29.jpg"
    assert _normalize_internal_epub_path(raw) == (
        "OEBPS/Images/Nabokov, Vladimir - Defense (Vintage, 1990).jpg"
    )


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


def test_get_epub_cover_path_epub3_cover_image_without_meta_name(epub_path):
    path = epub_path(build_epub3(cover_meta_name=False))
    assert get_epub_cover_path(path) == "OEBPS/cover.png"
    data = read_epub_cover(path)
    assert data.startswith(b"\x89PNG")


def test_read_epub_cover_falls_back_when_db_path_is_wrong(epub_path):
    path = epub_path(build_epub3())
    data = read_epub_cover(path, "OEBPS/does-not-exist.png")
    assert data.startswith(b"\x89PNG")


def test_read_epub_cover_xhtml_wrapper(epub_path):
    path = epub_path(build_epub3_xhtml_cover_wrapper())
    assert get_epub_cover_path(path) == "OEBPS/cover.xhtml"
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
    meta = extract_metadata(_epub.read_epub(path, options={"ignore_ncx": True}))
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
