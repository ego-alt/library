"""Comic archives: reading pages, and writing the library's own CBZs.

Every file in the library is a CBZ: pages in reading order named 001.webp,
002.webp…, a ComicInfo.xml, and a MetronInfo.xml when the issue came from a
provider. CBR and CB7 files are unpacked with bsdtar (libarchive), which reads
RAR (including RAR5) and 7z without the non-free unrar.
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from xml.etree import ElementTree as ET

from PIL import Image

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl")
_MIMETYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".jxl": "image/jxl",
}
# WebP can't be wider or taller than this.
WEBP_MAX_SIDE = 16383


class ArchiveError(Exception):
    """The file isn't a comic archive we can read."""


def natural_key(name: str):
    """'page2' before 'page10'."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _is_page(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return name.lower().endswith(IMAGE_EXTENSIONS) and not base.startswith(".") and "__MACOSX" not in name


def page_mimetype(name: str) -> str:
    return _MIMETYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def page_names(zf: zipfile.ZipFile) -> list[str]:
    return sorted((n for n in zf.namelist() if _is_page(n)), key=natural_key)


def read_page(path: str, index: int) -> tuple[bytes, str]:
    """The `index`th page of a CBZ, and its mimetype."""
    with zipfile.ZipFile(path) as zf:
        names = page_names(zf)
        if not 0 <= index < len(names):
            raise IndexError(index)
        return zf.read(names[index]), page_mimetype(names[index])


def page_count(path: str) -> int:
    with zipfile.ZipFile(path) as zf:
        return len(page_names(zf))


def read_comicinfo(path: str) -> dict:
    """ComicInfo.xml from a CBZ as {field: text}, or {} when there's none."""
    try:
        with zipfile.ZipFile(path) as zf:
            name = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower() == "comicinfo.xml"), None)
            if name is None:
                return {}
            root = ET.fromstring(zf.read(name))
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return {}
    return {child.tag: (child.text or "").strip() for child in root if len(child) == 0}


def _unpack(src: str, dest: str) -> None:
    """Unpack any comic archive into `dest`."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                # Refuse paths that would land outside dest.
                target = os.path.realpath(os.path.join(dest, name))
                if not target.startswith(os.path.realpath(dest) + os.sep):
                    continue
                if name.endswith("/"):
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as fin, open(target, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
        return
    if not shutil.which("bsdtar"):
        raise ArchiveError("Can't open RAR or 7z files: bsdtar isn't installed.")
    try:
        subprocess.run(["bsdtar", "-xf", src, "-C", dest], check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as e:
        raise ArchiveError(
            f"Couldn't unpack {os.path.basename(src)}: {e.stderr.decode(errors='replace').strip()[:200]}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ArchiveError(f"Unpacking {os.path.basename(src)} took too long.") from e


def _to_webp(data: bytes, quality: int) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("P", "PA") else "RGB")
        if max(im.size) > WEBP_MAX_SIDE:
            im.thumbnail((WEBP_MAX_SIDE, WEBP_MAX_SIDE))
        out = io.BytesIO()
        im.save(out, "WEBP", quality=quality, method=4)
        return out.getvalue()


def write_cbz(
    src: str,
    dest: str,
    *,
    webp: bool,
    quality: int = 82,
    metadata: Callable[[int], tuple[str | None, str | None]] | None = None,
) -> int:
    """Make the library's CBZ at `dest` from any comic archive at `src`.

    Pages are renamed to their reading order and, with `webp`, re-encoded
    (pages already in WebP are kept as they are; a page Pillow can't read is
    kept too). `metadata(page_count)` gives the ComicInfo.xml and
    MetronInfo.xml to embed. Returns the page count. `dest` appears whole or
    not at all."""
    with tempfile.TemporaryDirectory(prefix="comic-") as tmp:
        _unpack(src, tmp)
        pages = []
        for root, _dirs, files in os.walk(tmp):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, tmp)
                if _is_page(rel):
                    pages.append((rel, full))
        if not pages:
            raise ArchiveError(f"No pages in {os.path.basename(src)}.")
        pages.sort(key=lambda p: natural_key(p[0]))

        width = max(3, len(str(len(pages))))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        partial = f"{dest}.partial"
        try:
            with zipfile.ZipFile(partial, "w") as out:
                for i, (rel, full) in enumerate(pages, 1):
                    ext = os.path.splitext(rel)[1].lower()
                    with open(full, "rb") as f:
                        data = f.read()
                    if webp and ext != ".webp":
                        try:
                            data, ext = _to_webp(data, quality), ".webp"
                        except Exception:
                            pass
                    # Images are already compressed: store them.
                    out.writestr(
                        zipfile.ZipInfo(f"{i:0{width}d}{ext}", date_time=(2000, 1, 1, 0, 0, 0)),
                        data,
                        compress_type=zipfile.ZIP_STORED,
                    )
                comicinfo, metroninfo = metadata(len(pages)) if metadata else (None, None)
                if comicinfo:
                    out.writestr("ComicInfo.xml", comicinfo, compress_type=zipfile.ZIP_DEFLATED)
                if metroninfo:
                    out.writestr("MetronInfo.xml", metroninfo, compress_type=zipfile.ZIP_DEFLATED)
            os.replace(partial, dest)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        return len(pages)


def replace_metadata(path: str, comicinfo: str | None, metroninfo: str | None) -> None:
    """Rewrite a CBZ's ComicInfo.xml/MetronInfo.xml, keeping its pages."""
    partial = f"{path}.partial"
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(partial, "w") as zout:
            for item in zin.infolist():
                if item.filename.lower() in ("comicinfo.xml", "metroninfo.xml"):
                    continue
                zout.writestr(item, zin.read(item.filename), compress_type=item.compress_type)
            if comicinfo:
                zout.writestr("ComicInfo.xml", comicinfo, compress_type=zipfile.ZIP_DEFLATED)
            if metroninfo:
                zout.writestr("MetronInfo.xml", metroninfo, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(partial, path)
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def _xml(root: ET.Element) -> str:
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _add(parent: ET.Element, tag: str, value) -> ET.Element | None:
    if value in (None, ""):
        return None
    child = ET.SubElement(parent, tag)
    child.text = str(value)
    return child


def comicinfo_xml(issue, series, page_count: int, original_filename: str | None = None) -> str:
    """ComicInfo.xml (the Anansi v2.0 schema most readers use)."""
    root = ET.Element(
        "ComicInfo",
        {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance", "xmlns:xsd": "http://www.w3.org/2001/XMLSchema"},
    )
    _add(root, "Title", issue.title)
    _add(root, "Series", series.name)
    _add(root, "Number", issue.number)
    _add(root, "Count", series.issue_count)
    _add(root, "Volume", series.volume or series.start_year)
    _add(root, "Summary", issue.description or None)
    notes = []
    if original_filename:
        notes.append(f"Original filename: {original_filename}")
    if series.provider in ("comicvine", "metron"):
        notes.append(
            f"Tagged by Shelves from {'ComicVine' if series.provider == 'comicvine' else 'Metron'} (series {series.provider_id}, issue {issue.provider_id})."
        )
    _add(root, "Notes", " ".join(notes) or None)
    when = issue.cover_date or issue.store_date
    if when:
        _add(root, "Year", when.year)
        _add(root, "Month", when.month)
        _add(root, "Day", when.day)
    _add(root, "Publisher", series.publisher)
    if series.provider == "comicvine" and issue.provider_id:
        _add(root, "Web", f"https://comicvine.gamespot.com/issue/4000-{issue.provider_id}/")
    elif series.provider == "metron" and issue.provider_id:
        _add(root, "Web", f"https://metron.cloud/issue/{issue.provider_id}/")
    _add(root, "PageCount", page_count)
    if page_count:
        pages = ET.SubElement(root, "Pages")
        ET.SubElement(pages, "Page", {"Image": "0", "Type": "FrontCover"})
    return _xml(root)


def metroninfo_xml(issue, series, page_count: int, original_filename: str | None = None) -> str | None:
    """MetronInfo.xml (schema v1.0), for issues that came from a provider."""
    if series.provider not in ("comicvine", "metron") or not issue.provider_id:
        return None
    root = ET.Element(
        "MetronInfo",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "https://raw.githubusercontent.com/Metron-Project/metroninfo/master/schema/v1.0/MetronInfo.xsd",
        },
    )
    ids = ET.SubElement(root, "ID")
    source = "Comic Vine" if series.provider == "comicvine" else "Metron"
    _add(ids, "Primary", issue.provider_id).set("source", source)
    if series.publisher:
        publisher = ET.SubElement(root, "Publisher")
        _add(publisher, "Name", series.publisher)
    series_el = ET.SubElement(root, "Series")
    _add(series_el, "Name", series.name)
    _add(series_el, "Volume", series.volume)
    _add(series_el, "StartYear", series.start_year)
    _add(series_el, "IssueCount", series.issue_count)
    _add(root, "Number", issue.number)
    _add(root, "Summary", issue.description or None)
    if issue.cover_date:
        _add(root, "CoverDate", issue.cover_date.isoformat())
    if issue.store_date:
        _add(root, "StoreDate", issue.store_date.isoformat())
    _add(root, "PageCount", page_count)
    _add(root, "Notes", f"Original filename: {original_filename}" if original_filename else None)
    return _xml(root)


def first_page(path: str) -> bytes:
    data, _ = read_page(path, 0)
    return data
