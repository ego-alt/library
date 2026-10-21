"""Helpers to synthesize minimal EPUBs in memory for tests.

Tests only need EPUBs that exercise the parsing/serving code paths — they
don't need realistic content. Building them inline keeps the repo binary-free.
"""

import io
import zipfile
from textwrap import dedent

# A 1x1 transparent PNG, base64-decoded — enough to satisfy a cover lookup.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def _container_xml() -> str:
    return dedent("""\
        <?xml version="1.0"?>
        <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles>
            <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
          </rootfiles>
        </container>
    """)


def build_epub3(
    *,
    title: str = "Test Book",
    author: str = "Test Author",
    chapters: list[tuple[str, str]] | None = None,
    nav_entries: list[dict] | None = None,
    include_cover: bool = True,
    cover_meta_name: bool = True,
) -> bytes:
    """EPUB3 with a nav doc.

    chapters: [(filename, html_body)]
    nav_entries: [{"title": ..., "href": "ch1.xhtml", "children": [...]}]
    """
    chapters = chapters or [
        ("ch1.xhtml", "<h1>One</h1><p>chapter one</p>"),
        ("ch2.xhtml", "<h1>Two</h1><p>chapter two</p>"),
    ]
    if nav_entries is None:
        nav_entries = [
            {"title": f"Chapter {i + 1}", "href": fn, "children": []}
            for i, (fn, _) in enumerate(chapters)
        ]

    manifest_items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    spine_refs = ['<itemref idref="nav"/>']
    for i, (fn, _) in enumerate(chapters):
        item_id = f"ch{i}"
        manifest_items.append(
            f'<item id="{item_id}" href="{fn}" media-type="application/xhtml+xml"/>'
        )
        spine_refs.append(f'<itemref idref="{item_id}"/>')

    if include_cover:
        manifest_items.append(
            '<item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>'
        )
        cover_meta = (
            '<meta name="cover" content="cover-img"/>' if cover_meta_name else ""
        )
    else:
        cover_meta = ""

    opf = dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier id="id">test-{title}</dc:identifier>
            <dc:title>{title}</dc:title>
            <dc:creator>{author}</dc:creator>
            {cover_meta}
          </metadata>
          <manifest>
            {''.join(manifest_items)}
          </manifest>
          <spine>
            {''.join(spine_refs)}
          </spine>
        </package>
    """)

    nav = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc">'
    nav += _render_nav_ol(nav_entries)
    nav += "</nav></body></html>"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _container_xml())
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        for fn, body in chapters:
            z.writestr(
                f"OEBPS/{fn}",
                f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>',
            )
        if include_cover:
            z.writestr("OEBPS/cover.png", _TINY_PNG)
    return buf.getvalue()


def _render_nav_ol(entries: list[dict]) -> str:
    out = "<ol>"
    for e in entries:
        out += f'<li><a href="{e["href"]}">{e["title"]}</a>'
        if e.get("children"):
            out += _render_nav_ol(e["children"])
        out += "</li>"
    out += "</ol>"
    return out


def build_epub3_xhtml_cover_wrapper(
    *,
    title: str = "XHTML Cover Book",
    author: str = "Author",
) -> bytes:
    """EPUB3 where ``meta name=cover`` points at XHTML that embeds a PNG via ``<img>``."""
    chapters = [("ch1.xhtml", "<h1>One</h1><p>body</p>")]
    nav_entries = [{"title": "Chapter 1", "href": "ch1.xhtml", "children": []}]
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="cover-xhtml" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="cover-img" href="cover.png" media-type="image/png"/>',
    ]
    spine_refs = ['<itemref idref="cover-xhtml"/>', '<itemref idref="nav"/>']
    for i, (fn, _) in enumerate(chapters):
        item_id = f"ch{i}"
        manifest_items.append(
            f'<item id="{item_id}" href="{fn}" media-type="application/xhtml+xml"/>'
        )
        spine_refs.append(f'<itemref idref="{item_id}"/>')

    opf = dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier id="id">test-{title}</dc:identifier>
            <dc:title>{title}</dc:title>
            <dc:creator>{author}</dc:creator>
            <meta name="cover" content="cover-xhtml"/>
          </metadata>
          <manifest>
            {''.join(manifest_items)}
          </manifest>
          <spine>
            {''.join(spine_refs)}
          </spine>
        </package>
    """)

    nav = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc">'
    nav += _render_nav_ol(nav_entries)
    nav += "</nav></body></html>"

    cover_xhtml = """<?xml version="1.0"?>
    <html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>
    <body><div><img src="cover.png" alt="Cover"/></div></body></html>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _container_xml())
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/cover.xhtml", cover_xhtml)
        z.writestr("OEBPS/cover.png", _TINY_PNG)
        for fn, body in chapters:
            z.writestr(
                f"OEBPS/{fn}",
                f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>',
            )
    return buf.getvalue()


def build_epub2_ncx(
    *,
    title: str = "NCX Book",
    author: str = "NCX Author",
    chapters: list[tuple[str, str]] | None = None,
    nav_entries: list[dict] | None = None,
) -> bytes:
    """EPUB2 with toc.ncx (no nav doc)."""
    chapters = chapters or [
        ("ch1.xhtml", "<h1>One</h1>"),
        ("ch2.xhtml", "<h1>Two</h1>"),
    ]
    if nav_entries is None:
        nav_entries = [
            {"title": f"Section {i + 1}", "href": fn, "children": []}
            for i, (fn, _) in enumerate(chapters)
        ]

    manifest_items = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    spine_refs = []
    for i, (fn, _) in enumerate(chapters):
        item_id = f"ch{i}"
        manifest_items.append(
            f'<item id="{item_id}" href="{fn}" media-type="application/xhtml+xml"/>'
        )
        spine_refs.append(f'<itemref idref="{item_id}"/>')

    opf = dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier id="id">test-{title}</dc:identifier>
            <dc:title>{title}</dc:title>
            <dc:creator>{author}</dc:creator>
          </metadata>
          <manifest>{''.join(manifest_items)}</manifest>
          <spine toc="ncx">{''.join(spine_refs)}</spine>
        </package>
    """)

    ncx = (
        '<?xml version="1.0"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f"<head/><docTitle><text>{title}</text></docTitle>"
        f"<navMap>{_render_ncx_points(nav_entries)}</navMap></ncx>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _container_xml())
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        for fn, body in chapters:
            z.writestr(
                f"OEBPS/{fn}",
                f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>',
            )
    return buf.getvalue()


def _render_ncx_points(entries: list[dict], counter: list[int] | None = None) -> str:
    counter = counter or [0]
    out = ""
    for e in entries:
        counter[0] += 1
        nid = f"np{counter[0]}"
        out += (
            f'<navPoint id="{nid}">'
            f'<navLabel><text>{e["title"]}</text></navLabel>'
            f'<content src="{e["href"]}"/>'
        )
        if e.get("children"):
            out += _render_ncx_points(e["children"], counter)
        out += "</navPoint>"
    return out


def build_epub_no_toc() -> bytes:
    """EPUB with a manifest/spine but no working TOC — exercises the synthetic fallback."""
    chapters = [("ch1.xhtml", "<h1>A</h1>"), ("ch2.xhtml", "<h1>B</h1>")]
    return build_epub2_ncx(
        chapters=chapters,
        # NCX points at a file that's not in the spine
        nav_entries=[{"title": "Missing", "href": "doesnotexist.xhtml", "children": []}],
    )
