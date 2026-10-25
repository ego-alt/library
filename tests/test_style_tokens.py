"""The app's sizes come from tokens.css: no stylesheet sets a raw font size,
so the type scale can't creep back to a size a pixel from its neighbour."""
import pathlib
import re

CSS = pathlib.Path(__file__).resolve().parent.parent / "library" / "static" / "css"
# A token, inherited, or relative to the text around it (a book's headings, sub/sup).
ALLOWED = re.compile(r"var\(--(text-\w+|reader-font-size)[^)]*\)|inherit|[\d.]+(em|%)")


def test_font_sizes_come_from_tokens():
    raw = []
    for path in sorted(CSS.glob("*.css")):
        if path.name == "tokens.css":
            continue
        css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        for value in re.findall(r"font-size:\s*([^;}!]+)", css):
            if not ALLOWED.fullmatch(value.strip()):
                raw.append(f"{path.name}: font-size: {value.strip()}")
    assert not raw, "use a --text-* token from tokens.css:\n" + "\n".join(raw)


def test_type_scale_is_small():
    sizes = re.findall(r"--text-[\w-]+:", (CSS / "tokens.css").read_text())
    assert len(sizes) <= 5
