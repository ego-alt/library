"""Downloads (with Settings at its foot) is for admins: no page shows it to anyone else."""

from library.comics.models import ComicIssue, ComicSeries
from library.downloads.models import SKIPPED
from library.models import db
from tests.conftest import make_cbz


def test_readers_never_see_admin_links(standard_client, comic_dir, tmp_path, book):
    from library.comics import files
    s = ComicSeries(provider="local", provider_id="x", name="X", monitor="none")
    i = ComicIssue(series=s, number="1", sort_number=1, status=SKIPPED)
    db.session.add_all([s, i])
    db.session.commit()
    files.import_file(str(make_cbz(tmp_path / "X 001.cbz")), i)
    for path in ["/", "/comics/", f"/comics/series/{s.id}", f"/read/{book.filename}", f"/comics/read/{i.id}", "/downloads", "/settings"]:
        r = standard_client.get(path, follow_redirects=True)
        page = r.data.decode()
        assert r.status_code == 200, path
        for link in ('href="/downloads"', 'id="settingsForm"', 'id="addComics"'):
            assert link not in page, (path, link)
