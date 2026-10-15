import logging
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from urllib.parse import unquote

from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


namespaces = {
    "calibre": "http://calibre.kovidgoyal.net/2009/metadata",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "opf": "http://www.idpf.org/2007/opf",
    "u": "urn:oasis:names:tc:opendocument:xmlns:container",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def rotate_list(items: list, n: int) -> list:
    if n == 0:
        return items
    return items[-n:] + items[:-n]


def _normalize_internal_epub_path(path: str) -> str:
    """Normalize a path as stored in the DB / OPF for zipfile lookup.

    Zip member names use decoded path segments; some OPFs (e.g. Calibre) put
    percent-encoded ``href`` values in the manifest — importers may have stored
    those literally, so apply :func:`urllib.parse.unquote` here.
    """
    if not path:
        return path
    p = path.replace("\\", "/").lstrip("./")
    p = unquote(p)
    return posixpath.normpath(p).lstrip("/")


def _discover_cover_path_in_open_zip(z: zipfile.ZipFile) -> str:
    """Return the package-relative path inside the zip to the cover resource.

    Tries EPUB2 ``<meta name="cover" content="id"/>`` first, then EPUB3 manifest
    items marked ``properties="... cover-image ..."``.
    """
    t = etree.fromstring(z.read("META-INF/container.xml"))
    root_el = t.xpath("/u:container/u:rootfiles/u:rootfile", namespaces=namespaces)
    if not root_el:
        raise ValueError("EPUB container has no rootfile")
    rootfile_path = root_el[0].get("full-path")
    if not rootfile_path:
        raise ValueError("EPUB rootfile missing full-path attribute")
    rootfile_path = rootfile_path.replace("\\", "/")

    t = etree.fromstring(z.read(rootfile_path))
    opf_dir = posixpath.dirname(rootfile_path)

    href = None
    cover_meta = t.xpath("//opf:metadata/opf:meta[@name='cover']", namespaces=namespaces)
    if cover_meta:
        cover_id = cover_meta[0].get("content")
        if cover_id:
            for item in t.xpath("//opf:manifest/opf:item", namespaces=namespaces):
                if item.get("id") == cover_id:
                    href = item.get("href")
                    break

    if not href:
        for item in t.xpath("//opf:manifest/opf:item", namespaces=namespaces):
            props = (item.get("properties") or "").split()
            if "cover-image" in props:
                href = item.get("href")
                break

    if not href:
        raise ValueError("No cover reference in package document")

    href = unquote(href.strip())
    if not href:
        raise ValueError("Empty cover href in package document")

    return posixpath.normpath(posixpath.join(opf_dir, href)).lstrip("/")


def get_epub_cover_path(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        return _discover_cover_path_in_open_zip(z)


_COVER_MIMETYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def cover_mimetype(cover_path: str) -> str:
    ext = os.path.splitext(cover_path or "")[1].lower()
    return _COVER_MIMETYPES.get(ext, "image/jpeg")


def guess_cover_mimetype_from_bytes(data: bytes) -> str | None:
    """Infer image Content-Type from magic bytes (used when DB cover_path is stale)."""
    if not data or len(data) < 4:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    head = data.lstrip()[:800]
    if b"<svg" in head or (head.startswith(b"<?xml") and b"<svg" in data[:2000]):
        return "image/svg+xml"
    return None


def _cover_bytes_look_like_image(data: bytes) -> bool:
    return guess_cover_mimetype_from_bytes(data) is not None


def _might_be_markup(data: bytes) -> bool:
    s = data.lstrip()[:200]
    return s.startswith(b"<") or s.startswith(b"\xef\xbb\xbf<")


def _unwrap_html_cover_to_image(
    z: zipfile.ZipFile, wrapper_internal_path: str, raw: bytes
) -> bytes:
    """If the cover entry is an HTML/XHTML wrapper, follow the first image ref."""
    if not _might_be_markup(raw):
        return raw
    try:
        soup = BeautifulSoup(raw, "xml")
    except Exception:
        return raw
    base = posixpath.dirname(wrapper_internal_path.replace("\\", "/"))
    for tag in soup.find_all(["img", "image"]):
        src = tag.get("src") or tag.get("href")
        if not src or str(src).startswith("data:"):
            continue
        src = str(src).split("#")[0].strip()
        target = posixpath.normpath(posixpath.join(base, unquote(src))).lstrip("/")
        try:
            nested = z.read(target)
        except KeyError:
            continue
        if _cover_bytes_look_like_image(nested):
            return nested
    return raw


def read_epub_cover(epub_file_path: str, cover_path: str | None = None) -> bytes:
    """Return the raw bytes of an EPUB's cover image.

    Tries the path stored in the database first (when provided), then fresh
    discovery from the package document. Handles EPUB3 ``cover-image`` items and
    XHTML cover wrappers that reference a raster file.
    """
    with zipfile.ZipFile(epub_file_path) as z:
        try:
            discovered = _discover_cover_path_in_open_zip(z)
        except Exception as exc:
            logger.warning("Could not discover cover in %s: %s", epub_file_path, exc)
            discovered = None

        candidates: list[str] = []
        if cover_path:
            candidates.append(_normalize_internal_epub_path(cover_path))
        if discovered and discovered not in candidates:
            candidates.append(discovered)

        if not candidates:
            raise FileNotFoundError(f"No cover path for {epub_file_path}")

        last_error: Exception | None = None
        for internal in candidates:
            try:
                raw = z.read(internal)
            except KeyError as exc:
                last_error = exc
                logger.debug("Cover zip member missing %s: %s", epub_file_path, internal)
                continue
            data = _unwrap_html_cover_to_image(z, internal, raw)
            if _cover_bytes_look_like_image(data):
                return data

        if last_error:
            raise KeyError(
                f"Cover not found in EPUB {epub_file_path!r} (tried {candidates!r})"
            ) from last_error
        raise ValueError(
            f"No usable raster/SVG cover bytes in {epub_file_path!r} (tried {candidates!r})"
        )


def display_author(author: str | None) -> str:
    """How an author name is shown. Catalogue-style "Judt, Tony" reads as
    "Tony Judt"; anything that isn't a single "Last, First" pair (several
    authors, "Jr.", organisations) is left as stored. Empty -> "Unknown author"."""
    name = " ".join((author or "").split())
    if not name or name.lower() in ("unknown author", "unknown"):
        return "Unknown author"
    if name.count(",") == 1 and "&" not in name and " and " not in name.lower():
        last, first = (part.strip() for part in name.split(","))
        suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
        if last and first and first.lower() not in suffixes and len(first.split()) <= 3:
            return f"{first} {last}"
    return name


def make_thumbnail(image_bytes: bytes, width: int) -> bytes:
    """Downscale a raster cover to `width` px wide as WebP. Raises for formats
    Pillow can't read (e.g. SVG); callers fall back to the original bytes."""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        if img.width > width:
            height = round(img.height * width / img.width)
            img = img.resize((width, height), Image.LANCZOS)
        out = BytesIO()
        img.save(out, "WEBP", quality=80, method=4)
        return out.getvalue()


# Fallback cover colours: muted spines from the shelf palette, each paired
# with a light ink. Picked per book from a hash of the title, so a book keeps
# its colour.
_FALLBACK_COVERS = [
    ("#34495E", "#FFF1E5"),
    ("#8B6F47", "#FFF1E5"),
    ("#5F7F74", "#FFF1E5"),
    ("#7A5C6E", "#FFF1E5"),
    ("#4F6D8F", "#FFF1E5"),
]


def _wrap_words(text: str, max_chars: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    for word in (text or "").split():
        if lines and len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max_chars - 1].rstrip() + "…"
    return lines


def fallback_cover_svg(title: str, author: str) -> bytes:
    """A typographic 2:3 cover for books whose EPUB has none: title and author
    set in a serif on a coloured board, like a cloth-bound hardback."""
    from html import escape
    from zlib import crc32

    bg, ink = _FALLBACK_COVERS[crc32((title or "").encode()) % len(_FALLBACK_COVERS)]
    title_lines = _wrap_words(title or "Untitled", 16, 5)
    author_lines = _wrap_words(author or "", 24, 2)
    title_size = 40 if max(map(len, title_lines)) <= 12 else 34
    serif = "Georgia, 'Times New Roman', serif"
    line_gap = round(title_size * 1.15)
    tspans = "".join(
        f'<tspan x="40" dy="{0 if i == 0 else line_gap}">{escape(line)}</tspan>'
        for i, line in enumerate(title_lines)
    )
    author_tspans = "".join(
        f'<tspan x="40" dy="{0 if i == 0 else 28}">{escape(line)}</tspan>'
        for i, line in enumerate(author_lines)
    )
    svg = "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600"'
        ' width="400" height="600">',
        f'<rect width="400" height="600" fill="{bg}"/>',
        f'<rect x="20" y="20" width="360" height="560" fill="none" stroke="{ink}"'
        ' stroke-opacity="0.35" stroke-width="2"/>',
        f'<text x="40" y="{110 + title_size}" fill="{ink}" font-family="{serif}"'
        f' font-size="{title_size}" font-weight="600">{tspans}</text>',
        f'<line x1="40" x2="140" y1="470" y2="470" stroke="{ink}"'
        ' stroke-opacity="0.6" stroke-width="2"/>',
        f'<text x="40" y="510" fill="{ink}" fill-opacity="0.85" font-family="{serif}"'
        f' font-size="22" font-style="italic">{author_tspans}</text>',
        "</svg>",
    ])
    return svg.encode("utf-8")


_HTML_EXTENSIONS = (".html", ".xhtml", ".htm")


def epub_text_size(epub_file_path: str) -> int:
    """Total uncompressed bytes of HTML/XHTML content inside an EPUB.

    A cheap proxy for "book length" used to size spine thickness in the
    bookshelf view. Reads only the zip's central directory — no decompression,
    no parsing — so it's fast enough to compute on first request and cache.
    """
    total = 0
    try:
        with zipfile.ZipFile(epub_file_path) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(_HTML_EXTENSIONS):
                    total += info.file_size
    except (zipfile.BadZipFile, FileNotFoundError, OSError) as e:
        logger.warning(f"Could not measure text size for {epub_file_path}: {e}")
        return 0
    return total


def spine_chapter_sizes(epub_file_path: str) -> list[int]:
    """Uncompressed byte size of each XHTML spine item, in reading order.

    These are the weights for whole-book progress: a position inside chapter
    `i` maps to (sum of sizes before i + fraction * size of i) / total. Uses
    the same spine filtering as get_epub_structure so indices line up with
    Bookmark.chapter_index. Reads the OPF and the zip directory only.
    """
    with zipfile.ZipFile(epub_file_path) as z:
        container = etree.fromstring(z.read("META-INF/container.xml"))
        rootfile_path = container.xpath(
            "/u:container/u:rootfiles/u:rootfile", namespaces=namespaces
        )[0].get("full-path")
        rootfile_dir = os.path.dirname(rootfile_path)
        root = etree.fromstring(z.read(rootfile_path))
        manifest = {
            item.get("id"): item
            for item in root.xpath("//opf:manifest/opf:item", namespaces=namespaces)
        }
        sizes = []
        spine = root.xpath("//opf:spine/opf:itemref/@idref", namespaces=namespaces)
        for idref in spine:
            item = manifest.get(idref)
            if item is None or item.get("media-type") != "application/xhtml+xml":
                continue
            path = os.path.normpath(os.path.join(rootfile_dir, item.get("href")))
            try:
                sizes.append(z.getinfo(path).file_size)
            except KeyError:
                sizes.append(0)
        return sizes


def book_progress(
    chapter_sizes: list[int], chapter_index: int, position: float
) -> float:
    """Whole-book progress in [0, 1] from a (chapter, fraction-through-chapter)
    bookmark, weighting each chapter by its size."""
    total = sum(chapter_sizes)
    if total <= 0 or not chapter_sizes:
        return 0.0
    idx = max(0, min(chapter_index or 0, len(chapter_sizes) - 1))
    pos = max(0.0, min(position or 0.0, 1.0))
    done = sum(chapter_sizes[:idx]) + pos * chapter_sizes[idx]
    return max(0.0, min(done / total, 1.0))


def normalize_path(path):
    """Normalize image paths"""
    path = path.replace("../", "").replace("./", "")
    return path.split("images/", 1)[-1]


def _clean_title(text: str) -> str:
    """Collapse whitespace and trim a candidate title string."""
    return " ".join((text or "").split())


def _outside_nav(elem) -> bool:
    """True if `elem` is not contained inside a <nav> element. Avoids returning
    'Contents' as a chapter title for the contents page itself."""
    parent = elem.parent
    while parent is not None:
        if getattr(parent, "name", None) == "nav":
            return False
        parent = parent.parent
    return True


def get_chapter_title(item, soup):
    """Best-effort chapter title extraction.

    Tries (in order):
      1. epub:type=chapter|title|subtitle (strongest semantic signal)
      2. h1, then h2, then h3 (most-specific heading present)
      3. Common chapter-title CSS class / id
      4. <title> in <head> (often generic but better than nothing)
      5. Filename-derived from the spine item
      6. First short paragraph (under 60 chars)
    Returns None if nothing usable is found.
    """

    # 1. epub:type semantic markers
    for elem in soup.find_all(attrs={"epub:type": ["chapter", "title", "subtitle"]}):
        if not _outside_nav(elem):
            continue
        if title := _clean_title(elem.get_text()):
            return title

    # 2. Heading tags by specificity (h1 wins over h2 wins over h3). We skip
    # h4-h6 because at that depth they're almost always sub-section labels.
    for tag_name in ("h1", "h2", "h3"):
        for heading in soup.find_all(tag_name):
            if not _outside_nav(heading):
                continue
            if title := _clean_title(heading.get_text()):
                return title

    # 3. Common chapter-title class / id names
    title_pattern = re.compile(
        r"(?:^|[-_])(chapter[-_]?title|chaptertitle|chapter[-_]?heading"
        r"|section[-_]?title|heading|^title$)(?:[-_]|$)",
        re.IGNORECASE,
    )
    for elem in soup.find_all(class_=title_pattern):
        if not _outside_nav(elem):
            continue
        if title := _clean_title(elem.get_text()):
            return title
    for elem in soup.find_all(id=title_pattern):
        if not _outside_nav(elem):
            continue
        if title := _clean_title(elem.get_text()):
            return title

    # 4. <title> in <head>
    head_title = soup.find("title")
    if head_title:
        if title := _clean_title(head_title.get_text()):
            return title

    # 5. Filename-derived
    if hasattr(item, "get_name"):
        filename = item.get_name()
        basename = os.path.splitext(os.path.basename(filename))[0]
        clean_name = basename.replace("_", " ").replace("-", " ")
        for prefix in ("chapter", "ch", "section", "part"):
            if clean_name.lower().startswith(prefix):
                clean_name = clean_name[len(prefix):].strip()
        if clean_name:
            return clean_name.title()

    # 6. First short paragraph (under 60 chars — chapter epigraphs / openers)
    first_para = soup.find("p")
    if first_para:
        text = _clean_title(first_para.get_text())
        if text and len(text) < 60:
            return text

    return None


def extract_metadata(epub_book):
    """Extract metadata from an epub book."""
    try:
        # Get title, fallback to filename if not found
        title = epub_book.get_metadata("DC", "title")
        title = title[0][0] if title else "Unknown Title"

        # Get author, fallback to "Unknown Author" if not found
        author = epub_book.get_metadata("DC", "creator")
        author = author[0][0] if author else "Unknown Author"

        return {"title": title, "author": author}
    except Exception as e:
        logger.error(f"Error extracting metadata: {str(e)}")
        return None


def update_epub_cover(epub_file_path: str, new_cover_bytes: bytes) -> None:
    """Replace the cover image in the EPUB file with new cover bytes."""
    # Get the internal path for the cover image in the EPUB archive
    cover_path_inside = get_epub_cover_path(epub_file_path)

    # Create a temporary file that will become the updated EPUB
    temp_fd, temp_path = tempfile.mkstemp(suffix=".epub")
    os.close(temp_fd)

    with zipfile.ZipFile(epub_file_path, "r") as zin:
        with zipfile.ZipFile(temp_path, "w") as zout:
            for item in zin.infolist():
                if item.filename == cover_path_inside:
                    # Replace the cover image with the new image bytes
                    zout.writestr(item, new_cover_bytes)
                else:
                    # Copy all other original files as-is
                    zout.writestr(item, zin.read(item.filename))

    # Replace the original EPUB file with the updated version
    shutil.move(temp_path, epub_file_path)


_NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}


def _split_toc_href(href: str, doc_dir: str) -> tuple[str, str]:
    """Resolve a TOC href into (full path inside zip, fragment id)."""
    if not href:
        return "", ""
    path_part, _, section = href.partition("#")
    if not path_part:
        return "", section
    full = os.path.normpath(os.path.join(doc_dir, unquote(path_part)))
    return full, section


def _walk_nav_ol(ol, nav_dir: str) -> list[dict]:
    entries = []
    for li in ol.find_all("li", recursive=False):
        anchor = li.find(["a", "span"], recursive=False)
        if anchor is None:
            continue
        title = anchor.get_text(strip=True)
        href = anchor.get("href", "") if anchor.name == "a" else ""
        path, section = _split_toc_href(href, nav_dir)
        nested = li.find("ol", recursive=False)
        entries.append(
            {
                "title": title,
                "href": path,
                "section_id": section,
                "children": _walk_nav_ol(nested, nav_dir) if nested else [],
            }
        )
    return entries


def _parse_nav_html(content: bytes, nav_dir: str) -> list[dict]:
    soup = BeautifulSoup(content, "html.parser")
    nav = soup.find("nav", attrs={"epub:type": "toc"}) or soup.find("nav")
    if not nav:
        return []
    ol = nav.find("ol")
    return _walk_nav_ol(ol, nav_dir) if ol else []


def _walk_ncx_points(points, ncx_dir: str) -> list[dict]:
    entries = []
    for point in points:
        label = point.find("ncx:navLabel/ncx:text", namespaces=_NCX_NS)
        content = point.find("ncx:content", namespaces=_NCX_NS)
        if label is None or content is None:
            continue
        path, section = _split_toc_href(content.get("src", ""), ncx_dir)
        entries.append(
            {
                "title": (label.text or "").strip(),
                "href": path,
                "section_id": section,
                "children": _walk_ncx_points(
                    point.findall("ncx:navPoint", namespaces=_NCX_NS), ncx_dir
                ),
            }
        )
    return entries


def _read_epub_toc(z, opf_root, rootfile_dir: str, manifest, spine_elem) -> list[dict]:
    """Return raw TOC entries (with full zip paths). Prefers EPUB3 nav doc, falls back to EPUB2 NCX."""
    nav_item = next(
        (m for m in manifest.values() if "nav" in (m.get("properties") or "").split()),
        None,
    )
    if nav_item:
        nav_path = os.path.normpath(os.path.join(rootfile_dir, nav_item["href"]))
        try:
            return _parse_nav_html(z.read(nav_path), os.path.dirname(nav_path))
        except Exception as e:
            logger.warning(f"Failed to parse nav doc {nav_path}: {e}")

    ncx_id = spine_elem.get("toc")
    ncx_item = manifest.get(ncx_id) if ncx_id else None
    if not ncx_item:
        ncx_item = next(
            (m for m in manifest.values()
             if m.get("media-type") == "application/x-dtbncx+xml"),
            None,
        )
    if ncx_item:
        ncx_path = os.path.normpath(os.path.join(rootfile_dir, ncx_item["href"]))
        try:
            return _parse_ncx_points(
                etree.fromstring(z.read(ncx_path)).findall(
                    "ncx:navMap/ncx:navPoint", namespaces=_NCX_NS
                ),
                os.path.dirname(ncx_path),
            )
        except Exception as e:
            logger.warning(f"Failed to parse NCX {ncx_path}: {e}")

    return []


def _parse_ncx_points(points, ncx_dir: str) -> list[dict]:
    return _walk_ncx_points(points, ncx_dir)


_CONTENTS_KEYWORDS = {"contents", "table of contents", "toc"}
_CONTENTS_SCAN_LIMIT = 15  # contents pages are always front matter
_CONTENTS_MIN_RESOLVED = 3  # need at least this many spine matches to trust the page
_CONTENTS_MIN_RATIO = 0.8   # and ≥80% of all <a href> on the page must resolve


def _has_contents_marker(soup) -> bool:
    """True if the document looks like it presents itself as a Contents page.

    Recognises (in order):
      - <h1>/<h2>/<h3> whose text is just "Contents" / "Table of Contents"
      - <meta name="chapter-title" content="Contents"> (calibre's hint)
      - <title> in <head> mentioning Contents
      - Any short standalone text node ("CONTENTS" alone in a span/p/div)
    """
    body = soup.body or soup

    for heading in body.find_all(["h1", "h2", "h3"]):
        if " ".join(heading.get_text().split()).lower() in _CONTENTS_KEYWORDS:
            return True

    meta = soup.find("meta", attrs={"name": "chapter-title"})
    if meta and (meta.get("content") or "").strip().lower() in _CONTENTS_KEYWORDS:
        return True

    head_title = soup.find("title")
    if head_title and " ".join(head_title.get_text().split()).lower() in _CONTENTS_KEYWORDS:
        return True

    # Last resort: any standalone short text node literally saying "Contents".
    # Limited to short text so we don't trigger on prose mentioning the word.
    for text_node in body.find_all(string=True, limit=200):
        s = " ".join(text_node.split()).lower()
        if s in _CONTENTS_KEYWORDS:
            return True

    return False


def _find_contents_page(z, chapters, spine_paths) -> list[dict]:
    """Look for an in-content "Contents" page (very common in publisher EPUBs)
    and extract its <a href> links as TOC entries.

    Two-factor validation: the page must (a) present itself as a Contents page
    via heading/meta/title and (b) have most of its <a href>s resolve to spine
    items — filters out chapters that merely mention the word 'Contents'.
    """
    for ch in chapters[:_CONTENTS_SCAN_LIMIT]:
        try:
            content = z.read(ch["path"]).decode("utf-8", errors="replace")
        except KeyError:
            continue
        soup = BeautifulSoup(content, "html.parser")

        if not _has_contents_marker(soup):
            continue

        page_dir = os.path.dirname(ch["path"])
        entries: list[dict] = []
        total_with_href = 0
        for anchor in soup.find_all("a"):
            href = anchor.get("href")
            if not href or href.startswith("#"):
                continue
            total_with_href += 1
            path, section = _split_toc_href(href, page_dir)
            text = " ".join((anchor.get_text() or "").split())
            if path and text:
                entries.append({
                    "title": text,
                    "href": path,
                    "section_id": section,
                    "children": [],
                })

        resolved_count = sum(1 for e in entries if e["href"] in spine_paths)
        if resolved_count >= _CONTENTS_MIN_RESOLVED and total_with_href and (
            resolved_count / total_with_href >= _CONTENTS_MIN_RATIO
        ):
            logger.info(
                f"Using in-content Contents page at {ch['path']} "
                f"({resolved_count}/{total_with_href} links resolved)"
            )
            return entries

    return []


def _resolve_toc_to_spine(entries: list[dict], spine_paths: dict[str, int]) -> list[dict]:
    """Replace each entry's full-zip-path href with a spine index. Drop entries that don't
    map to anything in the spine and have no kept descendants."""
    resolved = []
    for entry in entries:
        spine_index = spine_paths.get(entry["href"], -1)
        children = _resolve_toc_to_spine(entry["children"], spine_paths)
        if spine_index < 0 and not children:
            continue
        title = entry["title"] or (
            f"Section {spine_index + 1}" if spine_index >= 0 else "Section"
        )
        resolved.append(
            {
                "title": title,
                "spine_index": spine_index,
                "section_id": entry["section_id"],
                "children": children,
            }
        )
    return resolved


def get_epub_structure(epub_path: str) -> dict:
    """Extract epub structure (spine, images, TOC) without loading full chapter content.

    The TOC resolution chain (nav doc → NCX → Contents page → synthetic) is
    documented in detail at docs/toc-resolution.md.
    """
    with zipfile.ZipFile(epub_path) as z:
        container = etree.fromstring(z.read("META-INF/container.xml"))
        rootfile_path = container.xpath(
            "/u:container/u:rootfiles/u:rootfile", namespaces=namespaces
        )[0].get("full-path")
        rootfile_dir = os.path.dirname(rootfile_path)

        root = etree.fromstring(z.read(rootfile_path))
        spine_elem = root.xpath("//opf:spine", namespaces=namespaces)[0]
        spine = root.xpath("//opf:spine/opf:itemref/@idref", namespaces=namespaces)

        manifest = {
            item.get("id"): {
                "href": item.get("href"),
                "media-type": item.get("media-type"),
                "properties": item.get("properties", ""),
            }
            for item in root.xpath("//opf:manifest/opf:item", namespaces=namespaces)
        }

        images = {
            normalize_path(manifest[id]["href"]): {
                "path": os.path.join(rootfile_dir, manifest[id]["href"]),
                "media-type": manifest[id]["media-type"],
            }
            for id, item in manifest.items()
            if item["media-type"].startswith("image/")
        }

        chapters = []
        spine_paths: dict[str, int] = {}
        for itemref in spine:
            if manifest[itemref]["media-type"] != "application/xhtml+xml":
                continue
            chapter_path = os.path.normpath(
                os.path.join(rootfile_dir, manifest[itemref]["href"])
            )
            spine_paths[chapter_path] = len(chapters)
            try:
                size = z.getinfo(chapter_path).file_size
            except KeyError:
                size = 0
            chapters.append(
                {
                    "id": itemref,
                    "path": chapter_path,
                    "index": len(chapters),
                    "size": size,
                }
            )

        # 1) Publisher's nav/NCX
        toc_raw = _read_epub_toc(z, root, rootfile_dir, manifest, spine_elem)
        toc = _resolve_toc_to_spine(toc_raw, spine_paths)

        # 2) An in-content Contents page (covers "calibre-y" EPUBs whose NCX is
        # broken but whose front matter still has a real reader-visible TOC)
        if not toc:
            contents_raw = _find_contents_page(z, chapters, spine_paths)
            toc = _resolve_toc_to_spine(contents_raw, spine_paths)

        # 3) Last resort: flat synthetic list, marked so the frontend can
        # progressively replace placeholders with extracted titles.
        if not toc:
            toc = [
                {
                    "title": f"Section {i + 1}",
                    "spine_index": i,
                    "section_id": "",
                    "children": [],
                    "synthetic": True,
                }
                for i in range(len(chapters))
            ]

        return {
            "chapters": chapters,
            "images": images,
            "image_count": len(images),
            "toc": toc,
            "spine_length": len(chapters),
            "chapter_sizes": [c["size"] for c in chapters],
        }


def process_chapter_content(
    epub_path: str, chapter_path: str, images: dict, asset_url_prefix: str
) -> dict:
    """Process a single chapter's content, rewriting image refs to URLs under
    asset_url_prefix (e.g. '/book_asset/<filename>/')."""
    with zipfile.ZipFile(epub_path) as z:
        content = z.read(chapter_path).decode("utf-8")
        soup = BeautifulSoup(content, "html.parser")

        title = get_chapter_title(None, soup)

        # Process internal links
        for element in soup.find_all("a"):
            if href := element.get("href"):
                if not href.startswith("#"):
                    href = href.split("#")
                    href_path = href[0]
                    section = href[1] if len(href) > 1 else ""

                    element["chapter-link"] = href_path
                    element["section-link"] = section
                    element["href"] = "javascript:void(0);"
                    element["onclick"] = "handleChapterLink(this)"

        # Rewrite image refs to point at the asset URL route
        image_attributes = ["src", "href", "xlink:href"]
        for element in soup.find_all(["img", "image", "svg"]):
            for attr in image_attributes:
                if image_path := element.get(attr):
                    try:
                        normalized_path = normalize_path(unquote(image_path))
                        if normalized_path in images:
                            element[attr] = (
                                asset_url_prefix
                                + images[normalized_path]["path"]
                            )
                            if element.name == "img":
                                element["loading"] = "lazy"
                    except Exception as e:
                        logger.warning(f"Failed to process image {image_path}: {e}")

        return {
            "title": title,
            "href": chapter_path.split("/")[-1],
            "content": str(soup.body) if soup.body else str(soup),
        }
