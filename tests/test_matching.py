from library.matching import rank_matches, score_book


class _Book:
    """Minimal stand-in for an ORM Book (rank_matches only needs title/author)."""

    def __init__(self, title, author, filename="f.epub"):
        self.title = title
        self.author = author
        self.filename = filename


# --- score_book -----------------------------------------------------------------


def test_exact_match_scores_one():
    assert score_book("Dune", "Frank Herbert", "Dune", "Frank Herbert") == 1.0


def test_author_order_and_initials_still_match():
    s = score_book("Harry Potter", "J.K. Rowling", "Harry Potter", "Rowling, J. K.")
    assert s > 0.95


def test_edition_title_difference_still_ranks_high():
    s = score_book(
        "Harry Potter and the Sorcerer's Stone", "J. K. Rowling",
        "Harry Potter and the Philosopher's Stone", "J. K. Rowling",
    )
    assert s >= 0.6


def test_unrelated_book_scores_low():
    assert score_book("Dune", "Frank Herbert", "The Hobbit", "J.R.R. Tolkien") < 0.4


def test_missing_author_falls_back_to_title_only():
    # A blank scanned author shouldn't drag down an otherwise perfect title.
    assert score_book("Dune", "", "Dune", "Frank Herbert") == 1.0


# --- rank_matches ---------------------------------------------------------------


def test_rank_matches_filters_and_sorts():
    books = [
        _Book("Dune", "Frank Herbert", "dune.epub"),
        _Book("Dune Messiah", "Frank Herbert", "messiah.epub"),
        _Book("The Hobbit", "J.R.R. Tolkien", "hobbit.epub"),
    ]
    ranked = rank_matches("Dune", "Frank Herbert", books, threshold=0.6)

    filenames = [b.filename for b, _ in ranked]
    assert filenames[0] == "dune.epub"          # exact match ranks first
    assert "hobbit.epub" not in filenames        # unrelated book filtered out

    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_matches_respects_limit():
    books = [_Book("Dune", "Frank Herbert", f"{i}.epub") for i in range(10)]
    ranked = rank_matches("Dune", "Frank Herbert", books, threshold=0.6, limit=3)
    assert len(ranked) == 3
