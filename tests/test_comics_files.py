import os
import shutil
import subprocess
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import pytest

from library import settings
from library.comics import archive, files
from library.comics.models import MONITOR_ALL, MONITOR_FUTURE, ComicIssue, ComicSeries
from library.comics.series import set_monitor, sync_issues
from library.downloads.models import DOWNLOADED, SKIPPED, WANTED
from library.models import db
from tests.conftest import make_cbz


@pytest.fixture
def series(app):
    s = ComicSeries(provider="comicvine", provider_id="123", name="Saga", start_year=2012, publisher="Image", issue_count=66, monitor=MONITOR_FUTURE)
    db.session.add(s)
    for n in (1, 2, 65, 66):
        db.session.add(ComicIssue(series=s, provider_id=str(1000 + n), number=str(n), sort_number=n, cover_date=date(2012 + n // 10, 3, 1), status=SKIPPED))
    db.session.commit()
    return s


def test_write_cbz_orders_converts_and_tags(app, tmp_path, series):
    src = make_cbz(tmp_path / "Saga 065 (2023) (Digital).cbz", pages=12)
    dest = tmp_path / "out.cbz"
    issue = series.issues[2]
    pages = archive.write_cbz(str(src), str(dest), webp=True, metadata=lambda n: (archive.comicinfo_xml(issue, series, n, src.name), archive.metroninfo_xml(issue, series, n, src.name)))
    assert pages == 12
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert names[:3] == ["001.webp", "002.webp", "003.webp"]
        assert names[11] == "012.webp"
        info = ET.fromstring(zf.read("ComicInfo.xml"))
        metron = ET.fromstring(zf.read("MetronInfo.xml"))
    assert info.findtext("Series") == "Saga"
    assert info.findtext("Number") == "65"
    assert info.findtext("PageCount") == "12"
    assert "Original filename: Saga 065 (2023) (Digital).cbz" in info.findtext("Notes")
    assert metron.find("ID/Primary").get("source") == "Comic Vine"
    assert metron.findtext("Series/Name") == "Saga"
    # page2.png was written before page10.png would be; natural order kept.
    first, _ = archive.read_page(str(dest), 0)
    assert first[:4] == b"RIFF"


def test_write_cbz_rejects_an_archive_without_pages(tmp_path):
    src = tmp_path / "empty.cbz"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("readme.txt", "nothing")
    with pytest.raises(archive.ArchiveError):
        archive.write_cbz(str(src), str(tmp_path / "out.cbz"), webp=False)
    assert not (tmp_path / "out.cbz").exists()


@pytest.mark.skipif(not shutil.which("bsdtar"), reason="needs bsdtar")
def test_write_cbz_reads_7z(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    with zipfile.ZipFile(make_cbz(tmp_path / "x.cbz", pages=2)) as zf:
        zf.extractall(pages)
    src = tmp_path / "x.cb7"
    subprocess.run(["bsdtar", "--format", "7zip", "-cf", str(src), "-C", str(pages), "."], check=True)
    assert archive.write_cbz(str(src), str(tmp_path / "out.cbz"), webp=False) == 2


def test_match_file_by_name_and_by_comicinfo(app, comic_dir, tmp_path, series):
    match = files.match_file(str(make_cbz(tmp_path / "Saga 065 (2023) (Digital) (Zone-Empire).cbz")))
    assert match.issue is not None and match.issue.number == "65"

    info = "<ComicInfo><Series>Saga</Series><Number>2</Number><Year>2012</Year></ComicInfo>"
    match = files.match_file(str(make_cbz(tmp_path / "random-name.cbz", comicinfo=info)))
    assert match.issue.number == "2"

    match = files.match_file(str(make_cbz(tmp_path / "Saga 099 (2030).cbz")))
    assert match.issue is None and match.series == series and "no issue #99" in match.reason

    match = files.match_file(str(make_cbz(tmp_path / "Paper Girls 001 (2015).cbz")))
    assert match.issue is None and match.series is None


def test_import_file_files_it_under_the_series(app, comic_dir, tmp_path, series):
    issue = series.issues[2]
    src = make_cbz(tmp_path / "Saga 065 (2023) (Digital).cbz")
    files.import_file(str(src), issue)
    assert issue.status == DOWNLOADED
    assert issue.filename == os.path.join("Image", "Saga (2012)", "Saga #065 (2018).cbz")
    assert issue.page_count == 3
    assert issue.original_filename == "Saga 065 (2023) (Digital).cbz"
    assert (comic_dir / issue.filename).exists()
    assert not src.exists()

    # A better copy replaces it.
    files.import_file(str(make_cbz(tmp_path / "again.cbz", pages=5)), issue)
    assert issue.page_count == 5
    assert len(list((comic_dir / "Image" / "Saga (2012)").iterdir())) == 1


def test_import_keeps_names_when_renaming_is_off(app, comic_dir, tmp_path, series):
    settings.set_many({"rename": False, "convert_webp": False})
    issue = series.issues[0]
    files.import_file(str(make_cbz(tmp_path / "saga_01_scan.cbz")), issue)
    assert os.path.basename(issue.filename) == "saga_01_scan.cbz"
    with zipfile.ZipFile(comic_dir / issue.filename) as zf:
        assert zf.namelist()[0] == "001.png"


def test_scan_import_dir(app, comic_dir, series):
    inbox = comic_dir / "_import"
    inbox.mkdir()
    make_cbz(inbox / "Saga 001 (2012).cbz")
    sub = inbox / "Saga.002.2012.Digital-Group"
    sub.mkdir()
    make_cbz(sub / "Saga.002.2012.Digital-Group.cbz")
    make_cbz(inbox / "Something Else 004 (2020).cbz")
    (inbox / "broken.cbr").write_bytes(b"not an archive")

    result = files.scan_import_dir()
    assert len(result["imported"]) == 2
    assert sorted(result["unmatched"]) == ["Something Else 004 (2020).cbz", "broken.cbr"]
    assert series.issues[0].status == DOWNLOADED and series.issues[1].status == DOWNLOADED


def test_sync_issues_on_first_add_wants_only_whats_coming(app):
    s = ComicSeries(provider="comicvine", provider_id="9", name="New Thing", monitor=MONITOR_FUTURE)
    db.session.add(s)
    today = date.today()
    rows = [
        {"provider_id": "1", "number": "1", "cover_date": today - timedelta(days=60)},
        {"provider_id": "2", "number": "2", "store_date": today + timedelta(days=7)},
        {"provider_id": "3", "number": "3"},
    ]
    assert sync_issues(s, rows, first_sync=True) == 3
    assert [i.status for i in s.issues] == [SKIPPED, WANTED, WANTED]

    # Later: a new issue that came out after the series was added is wanted.
    db.session.commit()
    rows.append({"provider_id": "4", "number": "4", "store_date": today})
    assert sync_issues(s, rows) == 1
    assert s.issues[-1].status == WANTED


def test_sync_issues_adopts_an_imported_issue_by_number(app):
    s = ComicSeries(provider="metron", provider_id="5", name="Thing", monitor=MONITOR_ALL)
    db.session.add(s)
    imported = ComicIssue(series=s, number="7", sort_number=7, filename="x.cbz", status=DOWNLOADED)
    db.session.add(imported)
    db.session.flush()
    sync_issues(s, [{"provider_id": "70", "number": "007", "title": "Seven"}])
    assert len(s.issues) == 1 and imported.provider_id == "70" and imported.title == "Seven"
    assert imported.status == DOWNLOADED


def test_set_monitor(app, series):
    set_monitor(series, MONITOR_ALL)
    assert all(i.status == WANTED for i in series.issues)
    series.issues[0].status = DOWNLOADED
    set_monitor(series, "none")
    assert [i.status for i in series.issues] == [DOWNLOADED, SKIPPED, SKIPPED, SKIPPED]
