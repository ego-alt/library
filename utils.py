import base64
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
import logging
from lxml import etree
import os
from urllib.parse import unquote
import zipfile


namespaces = {
   "calibre":"http://calibre.kovidgoyal.net/2009/metadata",
   "dc":"http://purl.org/dc/elements/1.1/",
   "dcterms":"http://purl.org/dc/terms/",
   "opf":"http://www.idpf.org/2007/opf",
   "u":"urn:oasis:names:tc:opendocument:xmlns:container",
   "xsi":"http://www.w3.org/2001/XMLSchema-instance",
}


def get_epub_cover(epub_path):
    with zipfile.ZipFile(epub_path) as z:
        # We load "META-INF/container.xml" using lxml.etree.fromString():
        t = etree.fromstring(z.read("META-INF/container.xml"))

        # Load the root path to find where static files are stored
        rootfile_path = t.xpath("/u:container/u:rootfiles/u:rootfile", namespaces=namespaces)[0].get("full-path")
        t = etree.fromstring(z.read(rootfile_path))

        # Find the cover image id and load the image
        cover_id = t.xpath("//opf:metadata/opf:meta[@name='cover']", namespaces=namespaces)[0].get("content")
        cover_href = t.xpath("//opf:manifest/opf:item[@id='" + cover_id + "']", namespaces=namespaces)[0].get("href")
        cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)
        return base64.b64encode(z.read(cover_path)).decode('utf-8')


def normalize_path(path):
    """Normalize image paths by removing '../' and './'"""
    return path.replace('../', '').replace('./', '')


def get_chapter_title(item, soup):
    """Extract chapter title using multiple fallback methods."""
    # Method 1: Check for heading tags
    title_tag = soup.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'title'])
    if title_tag:
        title = title_tag.get_text().strip()
        if title:
            return title

    # Method 2: Check epub:type attribute for common chapter indicators
    chapter_elements = soup.find_all(attrs={"epub:type": ["chapter", "title", "subtitle"]})
    if chapter_elements:
        for elem in chapter_elements:
            title = elem.get_text().strip()
            if title:
                return title

    # Method 3: Check for common class names or IDs
    common_title_identifiers = [
        "chapter-title", "chapterTitle", "chapter_title",
        "title", "heading", "chapter-heading", "section-title"
    ]
    for identifier in common_title_identifiers:
        # Check classes
        title_elem = soup.find(class_=identifier)
        if title_elem:
            title = title_elem.get_text().strip()
            if title:
                return title
        
        # Check IDs
        title_elem = soup.find(id=identifier)
        if title_elem:
            title = title_elem.get_text().strip()
            if title:
                return title

    # Method 4: Check item properties in the spine
    if hasattr(item, 'get_name'):
        filename = item.get_name()
        # Remove file extension and common prefixes
        basename = os.path.splitext(os.path.basename(filename))[0]
        # Clean up the filename
        clean_name = basename.replace('_', ' ').replace('-', ' ')
        # Remove common prefixes like 'chapter', 'section', etc.
        for prefix in ['chapter', 'ch', 'section', 'part']:
            if clean_name.lower().startswith(prefix):
                clean_name = clean_name[len(prefix):].strip()
        if clean_name:
            return clean_name.title()

    # Method 5: Look for the first substantial paragraph
    first_para = soup.find('p')
    if first_para:
        text = first_para.get_text().strip()
        # Only use if it's short enough to be a title (less than 100 chars)
        if text and len(text) < 100:
            return text

    return None


def get_epub_content(epub_dir, epub_path):
    book = ebooklib.epub.read_epub(os.path.join(epub_dir, epub_path))
    chapters = []
    images = {}
    
    # Extract images
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            try:
                image_data = base64.b64encode(item.content).decode('utf-8')
                normalized_path = normalize_path(item.file_name)
                images[normalized_path] = f"data:{item.media_type};base64,{image_data}"
                logging.debug(f"Stored image: {normalized_path}")
            except Exception as e:
                logging.error(f"Error processing image {item.file_name}: {str(e)}")
    
    # Get spine order
    spine_items = []
    for item in book.spine:
        if isinstance(item, tuple):
            spine_items.append(item[0])  # Handle tuples in spine
        else:
            spine_items.append(item)     # Handle direct items
    
    # Process chapters in spine order
    for item_id in spine_items:
        item = book.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            
            # Extract chapter title using the new function
            title = get_chapter_title(item, soup)
            
            # Process images
            for img in soup.find_all('img'):
                src = img.get('src')
                if src:
                    normalized_src = normalize_path(unquote(src))
                    if normalized_src in images:
                        img['src'] = images[normalized_src]
                        logging.debug(f"Updated image src: {normalized_src}")
                    else:
                        logging.warning(f"Image not found: {normalized_src}")
            
            chapters.append({
                'id': item.id,
                'title': title,
                'content': str(soup.body) if soup.body else str(soup)
            })
    
    metadata = book.get_metadata('DC', 'title')
    creator_metadata = book.get_metadata('DC', 'creator')
    
    return {
        'title': metadata[0][0] if metadata else "Untitled",
        'author': creator_metadata[0][0] if creator_metadata else "Unknown Author",
        'chapters': chapters,
        'image_count': len(images)
    } 
