"""Reading series, issue number and year out of comic filenames and release
titles, and comparing series names.

    "Batman 152 (2024) (Digital) (Zone-Empire).cbz"  -> Batman, 152, 2024
    "The.Amazing.Spider-Man.v6.001.2022.Digital.cbr" -> The Amazing Spider-Man, 1, 2022, v6
    "Absolute Batman 01 (of 12) (2024)"              -> Absolute Batman, 1, 2024
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

COMIC_EXTENSIONS = (".cbz", ".cbr", ".cb7", ".zip", ".rar", ".7z", ".cbt")

_YEAR = re.compile(r"^(19[3-9]\d|20[0-4]\d)$")
_BRACKETS = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_OF_N = re.compile(r"\(\s*of\s+\d+\s*\)", re.I)
_VOLUME = re.compile(r"\b(?:v|vol\.?|volume)\s*(\d{1,4})\b", re.I)
# An issue number: 1, 001, #1, 1.5, ½, -1, 1.MU, 1AU. Not a year.
_NUMBER = re.compile(r"(?:^|\s)#?(-?\d{1,4}(?:\.\d{1,2})?|½|¼|¾)(?:\.?([A-Za-z]{1,3}))?(?=\s|$)")
_TRADE_WORDS = re.compile(
    r"\b(tpb|trade paperback|hc|hardcover|omnibus|compendium|collection|graphic novel|gn)\b", re.I
)
_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75}


@dataclass
class ParsedName:
    series: str = ""
    number: str | None = None
    year: int | None = None
    volume: int | None = None
    annual: bool = False
    trade: bool = False
    tags: list[str] = field(default_factory=list)


def strip_extension(name: str) -> str:
    lower = name.lower()
    for ext in COMIC_EXTENSIONS:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


def normalize_number(number: str | None) -> str | None:
    """'001' -> '1', '1.0' -> '1', '1.50' -> '1.5'; suffixes kept ('1.MU' -> '1.MU')."""
    if number is None:
        return None
    number = str(number).strip().lstrip("#")
    if not number:
        return None
    if number in _FRACTIONS:
        return number
    match = re.match(r"^(-?)(\d+)(?:\.(\d+))?(.*)$", number)
    if not match:
        return number
    sign, whole, fraction, rest = match.groups()
    whole = str(int(whole))
    fraction = (fraction or "").rstrip("0")
    result = sign + whole + (f".{fraction}" if fraction else "")
    rest = rest.strip(". ")
    return f"{result}.{rest.upper()}" if rest else result


def sort_number(number: str | None) -> float:
    """A number to sort issues by; suffixed or odd numbers sort near their base."""
    if not number:
        return 0.0
    if number in _FRACTIONS:
        return _FRACTIONS[number]
    match = re.match(r"^-?\d+(?:\.\d+)?", number)
    if not match:
        return 0.0
    value = float(match.group(0))
    # 1.MU after 1 but before 2.
    return value + (0.001 if len(match.group(0)) < len(number) else 0)


def parse(name: str) -> ParsedName:
    """Read a filename or release title."""
    text = strip_extension(name.rsplit("/", 1)[-1])
    text = text.replace("_", " ")
    # Dotted scene names ("Saga.065.2023.Digital"): every dot is a space.
    if " " not in text.strip() and text.count(".") >= 2:
        text = text.replace(".", " ")
    result = ParsedName()
    text = _OF_N.sub(" ", text)

    for tag in _BRACKETS.findall(text):
        tag = tag.strip()
        if _YEAR.match(tag) and result.year is None:
            result.year = int(tag)
        elif tag:
            result.tags.append(tag)
    text = _BRACKETS.sub(" ", text)

    if match := _VOLUME.search(text):
        result.volume = int(match.group(1))
        text = text[: match.start()] + " " + text[match.end() :]

    if re.search(r"\bannual\b", text, re.I):
        result.annual = True
    if _TRADE_WORDS.search(text) or any(_TRADE_WORDS.search(t) for t in result.tags):
        result.trade = True

    # The issue number is the last number-shaped word with a series before it.
    # Bare years are the year wherever they are ("Saga 065 2023 Digital",
    # "Batman 2016 001"), and never part of the name.
    words = text.split()
    number_at = None
    for i in range(len(words) - 1, 0, -1):
        if _YEAR.match(words[i]):
            continue
        if _NUMBER.fullmatch(" " + words[i]) and any(
            (j == 0 or not _YEAR.match(w)) and w not in "-#" for j, w in enumerate(words[:i])
        ):
            number_at = i
            break
    if number_at is not None:
        match = _NUMBER.fullmatch(" " + words[number_at])
        result.number = normalize_number(match.group(1) + (f".{match.group(2)}" if match.group(2) else ""))
        tail = [w for w in words[number_at + 1 :] if not _YEAR.match(w)]
        if tail and " ".join(tail).strip(" -"):
            # "Batman 001 - The Court of Owls": the words after are its title.
            result.tags.insert(0, " ".join(tail).strip(" -"))
        before, after = words[:number_at], words[number_at + 1 :]
    else:
        before, after = words, []
    # A name can start with a year ("2000 AD"); anywhere else it's the year.
    for word in before[1:] + after:
        if _YEAR.match(word) and result.year is None:
            result.year = int(word)
    text = " ".join(w for i, w in enumerate(before) if i == 0 or not _YEAR.match(w))

    text = re.sub(r"\s+-\s*$|\s*#\s*$", "", text.strip())
    result.series = re.sub(r"\s+", " ", text).strip(" -")
    return result


def normalize_series(name: str) -> str:
    """For comparing series names: 'The Amazing Spider-Man' == 'amazing spiderman'."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\b(the|a|an)\b", " ", name)
    name = re.sub(r"\bannual\b", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def series_similarity(a: str, b: str) -> float:
    """0-1: how alike two series names are once normalized."""
    a, b = normalize_series(a), normalize_series(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a.replace(" ", "") == b.replace(" ", ""):
        return 0.98
    return SequenceMatcher(None, a, b).ratio()


def is_comic_file(name: str) -> bool:
    return name.lower().endswith(COMIC_EXTENSIONS)


def safe_filename(name: str) -> str:
    """Keep a name usable on exFAT and Windows: no :*?"<>|/\\ or trailing dots."""
    name = re.sub(r'[:*?"<>|/\\]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or "Untitled"
