import base64
import ebooklib
from lxml import etree
import os
import sys
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


def get_epub_content(epub_path):
    book = ebooklib.epub.read_epub(epub_path)
    book_html = [item for item in book.get_items() if item.get_type()==ebooklib.ITEM_DOCUMENT]
    return [html.get_body_content() for html in book_html]
