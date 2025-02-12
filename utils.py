import base64
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
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


def get_epub_cover(epub_file_path: str, cover_path: str = None) -> str:
    if cover_path is None:
        cover_path = get_epub_cover_path(epub_file_path)

    with zipfile.ZipFile(epub_file_path) as z:
        with z.open(cover_path) as f:
            return base64.b64encode(f.read()).decode("utf-8")


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


def get_epub_structure(epub_path: str) -> dict:
    """Extract epub structure without loading full content."""
    with zipfile.ZipFile(epub_path) as z:
        # Get container.xml to find the rootfile
        container = etree.fromstring(z.read("META-INF/container.xml"))
        rootfile_path = container.xpath(
            "/u:container/u:rootfiles/u:rootfile", namespaces=namespaces
        )[0].get("full-path")

        # Parse the rootfile (content.opf usually)
        root = etree.fromstring(z.read(rootfile_path))

        # Get spine order
        spine = root.xpath("//opf:spine/opf:itemref/@idref", namespaces=namespaces)

        # Get manifest items (mapping of id -> href)
        manifest = {
            item.get("id"): {
                "href": item.get("href"),
                "media-type": item.get("media-type"),
            }
            for item in root.xpath("//opf:manifest/opf:item", namespaces=namespaces)
        }

        # Get image items with their paths and media types
        images = {
            normalize_path(manifest[id]["href"]): {
                "path": os.path.join(
                    os.path.dirname(rootfile_path), manifest[id]["href"]
                ),
                "media-type": manifest[id]["media-type"],
            }
            for id, item in manifest.items()
            if item["media-type"].startswith("image/")
        }

        # Get spine items in order WITHOUT loading content
        chapters = [
            {
                "id": itemref,
                "path": os.path.join(
                    os.path.dirname(rootfile_path), manifest[itemref]["href"]
                ),
                "index": idx,  # Add index for default title
            }
            for idx, itemref in enumerate(spine)
            if manifest[itemref]["media-type"] == "application/xhtml+xml"
        ]

        return {"chapters": chapters, "images": images, "image_count": len(images)}


def process_chapter_content(epub_path: str, chapter_path: str, images: dict) -> dict:
    """Process a single chapter's content."""
    with zipfile.ZipFile(epub_path) as z:
        content = z.read(chapter_path).decode("utf-8")
        soup = BeautifulSoup(content, "html.parser")

        # Extract chapter title using multiple fallback methods
        title = get_chapter_title(None, soup)

        # Process any elements that might contain image references
        image_attributes = ['src', 'href', 'xlink:href']
        for element in soup.find_all(['img', 'image', 'link[rel="coverpage"]', 'svg']):
            for attr in image_attributes:
                if image_path := element.get(attr):
                    try:
                        normalized_path = normalize_path(unquote(image_path))
                        if normalized_path in images:
                            image_data = z.read(images[normalized_path]["path"])
                            element[attr] = (
                                f"data:{images[normalized_path]['media-type']};base64,"
                                f"{base64.b64encode(image_data).decode('utf-8')}"
                            )
                            if element.name == "img":
                                element["loading"] = "lazy"
                    except Exception as e:
                        logger.warning(f"Failed to process image {image_path}: {e}")

        return {"title": title, "content": str(soup.body) if soup.body else str(soup)}
