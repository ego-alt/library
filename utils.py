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
    
    # Process chapters
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            
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
