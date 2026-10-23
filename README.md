# Shelves

A personal EPUB library and reader for the home stack: covers hung on a warmly lit gallery wall, and a calm, book-like page for reading them.

![Shelves](images/shelves-2026-10.png)

<p>
  <img src="images/shelves-night-2026-10.png" alt="The gallery at night" width="49%">
  <img src="images/book-details-2026-10.png" alt="A book's details" width="49%">
</p>

![The reader, with a footnote open](images/reader-2026-10.png)

<p>
  <img src="images/reader-pages-sepia-2026-10.png" alt="Two-page spread in Sepia, with the reading settings open" width="49%">
  <img src="images/reader-pages-night-2026-10.png" alt="Two-page spread at night" width="49%">
</p>

![On a phone: the library by day and night, a footnote, and a chapter opening](images/phone-2026-10.png)

## Features

- **The gallery**: covers with title, author and how far you've read, five to a row on a laptop. It opens on what you're reading.
- **Search and filter** across titles, authors, genres and tags; *Unread*, *Reading* and *Finished*.
- **The reader**: continuous scroll or two-page spreads, no toolbars while you read, the chapter and time left in the margins. Text size, spacing, width and four themes (Day, Sepia, Night, Black) under `Aa`.
- **Footnotes** open beside their marker, and any jump inside the book offers a way back.
- **Ask and Explain**: select text to ask about it, or for a definition or translation in context (Claude; needs `ANTHROPIC_API_KEY`).
- **Read aloud** with your device's own voices (free, no account): the sentence being read is highlighted, and the pages turn or scroll to keep up. English, Mandarin and Cantonese, each from the book's language tags; a book's Chinese can be set to read as Mandarin or Cantonese, and each language's voice chosen, under `Aa`. Tap a sentence to read from there; `L` starts and pauses.
- **Vertical text** for Chinese and Japanese books (直排): lines top to bottom, right to left, pages turning leftwards, with one- and two-digit numbers upright. On by default when the book asks for it, and set per book under `Aa`.
- **Your place everywhere**: progress syncs across devices, and the paragraph you stopped at is marked when you return.
- **Managing books**: + beside the search (or drop one on the page) adds an EPUB, checked in its details card before it joins; edit details and covers, tag books, mark them private.
- **Safe edits**: deletes go to a 30-day trash with Undo.
- **Installable**, and the last 12 books you opened stay readable offline. `?` lists the keyboard shortcuts.

## Comics

Comics (`/comics/`) work like the books: everyone signed in sees the series there are files for, the ones you're partway through first, with a search box. A cover picks up where you left off; ⋯ opens the series: a compact header (how many are here and read, one button to continue) and its issues as small covers, each with a menu (press and hold on a phone).

- **Files**: comics are matched to their issue (by ComicInfo.xml or filename) and written as CBZs with WebP pages, a ComicInfo.xml and a MetronInfo.xml (the original filename is kept in the notes), under `<Publisher>/<Series (Year)>/<Series> #001 (Year).cbz`.
- **The reader**: one page, two-page spreads (the cover alone, wide pages alone) or one long scroll; fit to height or width; right to left for manga; tap, swipe or the arrow keys. Your page is saved, and the next issue is a tap away at the end.
- **For admins**, a series' missing issues show greyed out, saying what each is waiting for; its menu finds it now, chooses a release, skips it or adds a file. The header says which issues are being got (Change), and ⋯ › Choose issues wants or skips several.
- **Adding a comic**: + beside the search (or drop one on the page) takes one file and shows what it matched, in the same card a book gets, to check the series and number before it's added.

## Getting books and comics (admins)

- **Asking**: search the books or comics shelf, then "Get “dune”" under the results looks on Open Library (books) or ComicVine/Metron (series). Tap a book to ask for it (with Undo); tap a series to follow it (new issues from then on; the series page changes that).
- **Wanted books and issues are searched for** every few hours on your Newznab (usenet) and Torznab (torrent, via Prowlarr or Jackett) indexers, in their ebook (7020) or comics (7030) categories. The best release goes to SABnzbd or qBittorrent, filed under the client's books or comics category. Books need the title's words and the author's surname and an EPUB (audiobooks, PDFs and collections are skipped); comics are matched on series, issue number and year. A release that failed isn't downloaded again for the same thing; **Choose a release** shows every one and why each fits or doesn't.
- **Downloads** (the clock in the bar, `/downloads`): what's downloading, a line each (failures that need you on top, stalled ones named), and everything wanted (a line per book, a group per comic series).
- **Settings** (the tab beside Downloads, `/settings`): indexers, download clients, where finished downloads are, how releases are chosen (with a size limit for books and one for comics), ComicVine/Metron and how comic files are written.

One background worker does it all, in one gunicorn process (a file lock picks it), from the first request after a restart.

## Run it

```sh
uv sync
cp .env.example .env                                  # set SECRET_KEY and BOOK_DIR
mkdir -p "$BOOK_DIR"
uv run flask db upgrade
uv run flask create-user <username> <password> --role admin
uv run flask run --port 8002                          # http://127.0.0.1:8002
```

Or with Docker: `docker compose up -d`.

Tests and lint: `uv run pytest` and `uvx ruff check .`

### Settings

| Variable | Does |
|---|---|
| `SECRET_KEY` | Signs sessions (required) |
| `BOOK_DIR` | Where the EPUBs live (must exist) |
| `ANTHROPIC_API_KEY` | Turns on Ask and Explain (optional) |
| `TRASH_RETENTION_DAYS` | How long deleted books are kept (default 30) |
| `COMIC_DIR` | Where comics live (default `instance/comics`) |
| `COMICVINE_API_KEY`, `METRON_USERNAME`, `METRON_PASSWORD` | Metadata, if not set in the app |

## Home stack

Served at `/library/` behind the [dashboard](../dashboard)'s nginx, which signs people in and passes the user on. Set:

```sh
AUTH_PROXY_HEADER=X-Forwarded-User
APPLICATION_ROOT=/library
```

Leave both unset for standalone development. Accounts are created on first visit.

Commits merged to `master` that pass CI deploy to the Pi on their own (see the dashboard README). The container applies database migrations when it starts; release notes are in [`MIGRATION.md`](MIGRATION.md).

## Commands

```sh
uv run flask import-books --directory <path>                # add every EPUB in a folder
uv run flask create-user <username> <password> [--role admin]
uv run flask refresh-cover-paths                            # re-find each book's cover
uv run flask purge-trash [--days 30]                        # empty the trash (also runs on delete)
uv run flask backup-db --to <path> [--keep N]               # consistent SQLite snapshot while running
```

Cover thumbnails (`instance/thumbs/`), caches (`instance/cache/`) and pending uploads (`BOOK_DIR/.incoming/`) can all be deleted safely. Planned work is in [`docs/roadmap.md`](docs/roadmap.md).
