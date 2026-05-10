from bs4 import BeautifulSoup
import logging
from lxml import etree
import os
from urllib.parse import unquote
import zipfile
import tempfile
import shutil


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


def rotate_list(l: list, n: int) -> list:
    if n == 0:
        return l
    return l[-n:] + l[:-n]


def get_epub_cover_path(path: str):
    with zipfile.ZipFile(path) as z:
        # Load container.xml to find the root file
        t = etree.fromstring(z.read("META-INF/container.xml"))
        rootfile_path = t.xpath(
            "/u:container/u:rootfiles/u:rootfile", namespaces=namespaces
        )[0].get("full-path")

        # Load the root file to find cover image details
        t = etree.fromstring(z.read(rootfile_path))
        cover_id = t.xpath(
            "//opf:metadata/opf:meta[@name='cover']", namespaces=namespaces
        )[0].get("content")
        cover_href = t.xpath(
            "//opf:manifest/opf:item[@id='" + cover_id + "']", namespaces=namespaces
        )[0].get("href")

        # Get the cover image path and load it
        cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)

    return cover_path


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


def read_epub_cover(epub_file_path: str, cover_path: str = None) -> bytes:
    """Return the raw bytes of an EPUB's cover image."""
    if cover_path is None:
        cover_path = get_epub_cover_path(epub_file_path)
    with zipfile.ZipFile(epub_file_path) as z:
        with z.open(cover_path) as f:
            return f.read()


def normalize_path(path):
    """Normalize image paths"""
    path = path.replace("../", "").replace("./", "")
    return path.split("images/", 1)[-1]


def get_chapter_title(item, soup):
    """Extract chapter title using multiple fallback methods."""

    # Method 1: Check for heading tags
    title_tag = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if title_tag:
        title = title_tag.get_text().strip()
        if title:
            return title

    # Method 2: Check epub:type attribute for common chapter indicators
    chapter_elements = soup.find_all(
        attrs={"epub:type": ["chapter", "title", "subtitle"]}
    )
    if chapter_elements:
        for elem in chapter_elements:
            title = elem.get_text().strip()
            if title:
                return title

    # Method 3: Check for common class names or IDs
    common_title_identifiers = [
        "chapter-title",
        "chapterTitle",
        "chapter_title",
        "title",
        "heading",
        "chapter-heading",
        "section-title",
    ]
    for identifier in common_title_identifiers:
        title_elem = soup.find(class_=identifier) or soup.find(id=identifier)
        if title_elem:
            title = title_elem.get_text().strip()
            if title:
                return title

    # Method 4: Check item properties in the spine
    if hasattr(item, "get_name"):
        filename = item.get_name()
        basename = os.path.splitext(os.path.basename(filename))[0]
        clean_name = basename.replace("_", " ").replace("-", " ")
        for prefix in ["chapter", "ch", "section", "part"]:
            if clean_name.lower().startswith(prefix):
                clean_name = clean_name[len(prefix) :].strip()

        if clean_name:
            return clean_name.title()

    # Method 5: Look for the first substantial paragraph (under 100 characters)
    first_para = soup.find("p")
    if first_para:
        text = first_para.get_text().strip()
        if text and len(text) < 25:
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
    """Extract epub structure (spine, images, TOC) without loading full chapter content."""
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
            chapters.append(
                {"id": itemref, "path": chapter_path, "index": len(chapters)}
            )

        toc_raw = _read_epub_toc(z, root, rootfile_dir, manifest, spine_elem)
        toc = _resolve_toc_to_spine(toc_raw, spine_paths)

        # Fall back to a flat synthetic TOC for books with no nav/NCX.
        # Mark entries `synthetic` so the frontend can replace the placeholder
        # title with the real one once each chapter's content streams in.
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
