"""Each status has one owner: a download's is changed only in
downloads/pipeline.py, a wanted issue or book's only through the functions in
downloads/models.py."""

import pathlib
import re

LIBRARY = pathlib.Path(__file__).resolve().parent.parent / "library"
WRITE = re.compile(r"(\w+)\.status\s*=[^=]")


def _writes():
    for path in LIBRARY.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for name in WRITE.findall(line):
                yield path.relative_to(LIBRARY).as_posix(), n, name


def test_only_the_pipeline_changes_a_download():
    assert [f"{p}:{n}" for p, n, name in _writes() if name == "download" and p != "downloads/pipeline.py"] == []


def test_only_downloads_models_changes_a_wanted_thing():
    # Reading progress (a bookmark's status) is its own thing.
    assert [f"{p}:{n} {name}" for p, n, name in _writes() if name not in ("download", "bookmark") and p != "downloads/models.py"] == []
