import pytest

from library.comics.names import (
    normalize_number,
    parse,
    safe_filename,
    series_similarity,
    sort_number,
)


@pytest.mark.parametrize("name, series, number, year, volume", [
    ("Batman 152 (2024) (Digital) (Zone-Empire).cbz", "Batman", "152", 2024, None),
    ("The.Amazing.Spider-Man.v6.001.2022.Digital.cbr", "The Amazing Spider-Man", "1", 2022, 6),
    ("Absolute Batman 01 (of 12) (2024)", "Absolute Batman", "1", 2024, None),
    ("Saga 065 2023 Digital", "Saga", "65", 2023, None),
    ("Batman #152 (2024).cbz", "Batman", "152", 2024, None),
    ("Batman v3 152 (2024)", "Batman", "152", 2024, 3),
    ("Invincible Universe - Battle Beast 007 (2025) (digital)", "Invincible Universe - Battle Beast", "7", 2025, None),
    ("Batman 001 - The Court of Owls (2011)", "Batman", "1", 2011, None),
    ("2000 AD 2350 (2023)", "2000 AD", "2350", 2023, None),
    ("Lobo 001.MU (2025)", "Lobo", "1.MU", 2025, None),
    ("Batman 1.5 (2020)", "Batman", "1.5", 2020, None),
    ("Batman 0 (1994)", "Batman", "0", 1994, None),
    ("Batman 2016 001", "Batman", "1", 2016, None),
    ("Witchblade_003_(2025)_(Digital).cbz", "Witchblade", "3", 2025, None),
    ("G.I. Joe - A Real American Hero 300 (2023)", "G.I. Joe - A Real American Hero", "300", 2023, None),
    ("Spawn 350", "Spawn", "350", None, None),
])
def test_parse(name, series, number, year, volume):
    parsed = parse(name)
    assert (parsed.series, parsed.number, parsed.year, parsed.volume) == (series, number, year, volume)


def test_parse_flags_annuals_and_trades():
    assert parse("Uncanny X-Men Annual 001 (2026)").annual
    assert not parse("Uncanny X-Men 001 (2026)").annual
    trade = parse("Batman Vol. 01 - Court of Owls (2012) (TPB)")
    assert trade.trade and trade.number is None


@pytest.mark.parametrize("raw, normal", [("001", "1"), ("1.0", "1"), ("1.50", "1.5"), ("#12", "12"), ("1.mu", "1.MU"), ("½", "½"), ("-1", "-1"), ("", None)])
def test_normalize_number(raw, normal):
    assert normalize_number(raw) == normal


def test_sort_number_orders_odd_numbers():
    numbers = ["2", "1.MU", "½", "1", "10", "1.5", "0"]
    assert sorted(numbers, key=sort_number) == ["0", "½", "1", "1.MU", "1.5", "2", "10"]


def test_series_similarity():
    assert series_similarity("The Amazing Spider-Man", "Amazing Spiderman") == 1.0
    assert series_similarity("G.I. Joe: A Real American Hero", "G.I. Joe - A Real American Hero") == 1.0
    assert series_similarity("Batman", "Absolute Batman") < 0.86


def test_safe_filename():
    assert safe_filename('What If...? / Who: "Me"') == "What If... Who Me"
