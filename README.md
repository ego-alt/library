# Shelves

A self-hosted EPUB library and reader. It runs on its own or behind the home stack's [dashboard](../dashboard), which handles sign-in.

![The library by day](images/shelves-2026-10.png)

## Features

### Library

- **Cover gallery.** Covers keep their original 2:3 shape, five per row on a laptop and fewer as the window narrows. Each label shows the title, the author and, for books in progress, how far you've read. A bookshelf view of spines is also available.
- **Opens on Reading.** When you have books in progress, the library opens on *Reading*, most recent first.
- **Search and filter.** One search box matches titles, authors, genres and your tags. Filters cover *All*, *Unread*, *Reading* and *Finished*.
- **Book management.**
  - Add EPUBs with **+** or by dropping files onto the page; a single book opens a review panel before it's added.
  - Edit details and covers, tag books, and mark books private (admins only).
  - Deleting moves a book to a 30-day trash with **Undo**.
- **Day and night themes.** At night, covers are dimmed until you hover over them.

![The library at night](images/shelves-night-2026-10.png)

### Reader

- **Layout.**
  - Flat page colour with softened contrast: about 10:1 by day and 8.6:1 at night.
  - Lines of 70–85 characters, 1.7 line spacing, hyphenation.
  - Continuous scroll, or pages with two-page spreads on wide screens.
- **Time left.** The status bar shows the minutes left in the chapter and in the book, estimated from your own reading speed on that device.
- **Footnotes in place.** A note opens in a pop-up beside its marker. Any other jump inside the book offers **↩ Back to where you were**.
- **Book styling.** Each book keeps its own centred titles, italics, small caps and poem indents. Its fonts, colours and spacing are replaced with the reader's.
- **Ask and Explain.** Select text to ask a question about it, or to get a definition, translation or short explanation in context. This uses Claude and needs `ANTHROPIC_API_KEY`.
- **Your place everywhere.** Progress is saved as you read and synced across devices when you're signed in.

![The reader, with a footnote open](images/reader-2026-10.png)

### Phones and offline

- Touch layout: large tap targets, bottom sheets, and press-and-hold for a book's details.
- Installable as an app. The last 12 books you opened stay readable offline.
- Keyboard shortcuts on desktop; press `?` in the reader for the full list.

![On a phone: the library by day and night, a footnote, and a chapter opening](images/phone-2026-10.png)

## Getting started

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env        # then set SECRET_KEY and BOOK_DIR
mkdir -p "$BOOK_DIR"
uv run flask db upgrade
uv run flask run --port=8002
```

Open http://127.0.0.1:8002. To create the first account:

```sh
uv run flask create-user <username> <password> --role admin
```

To run with Docker instead: `docker compose up -d`.

### Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs sessions. Required. |
| `BOOK_DIR` | Folder holding the EPUB files. Must exist. |
| `ANTHROPIC_API_KEY` | Enables Ask and Explain. Optional. |
| `AUTH_PROXY_HEADER` | Trust a sign-in header from a proxy, e.g. `X-Forwarded-User`. Optional. |
| `APPLICATION_ROOT` | Path the app is served under, e.g. `/library`. Optional. |
| `TRASH_RETENTION_DAYS` | How long deleted books are kept (default 30). Optional. |

### Development

```sh
uv run pytest            # tests
uvx ruff check .         # lint
```

## Behind the dashboard

In the home stack, Shelves is served at `/library/` behind the dashboard's nginx, which signs people in and passes the username on. Set `AUTH_PROXY_HEADER=X-Forwarded-User` and `APPLICATION_ROOT=/library`. Accounts are created automatically on first visit.

Commits merged to `master` that pass CI deploy to the Pi automatically (see the dashboard's [`docs/DEPLOY.md`](../dashboard/docs/DEPLOY.md)). The container applies database migrations on start. Release-specific notes are in [`MIGRATION.md`](MIGRATION.md).

## Commands

| Command | Purpose |
|---|---|
| `flask import-books --directory <path>` | Add every EPUB in a folder |
| `flask create-user <username> <password> [--role admin]` | Create an account |
| `flask refresh-cover-paths` | Re-scan where each book's cover is stored |
| `flask purge-trash [--days N]` | Permanently remove books deleted more than *N* days ago (also runs automatically on delete) |
| `flask backup-db --to <path> [--keep N]` | Take a consistent SQLite snapshot while the app is running |

Prefix each with `uv run`. The app also writes cover thumbnails to `instance/thumbs/`, caches to `instance/cache/`, and pending uploads to `BOOK_DIR/.incoming/`. All three can be safely deleted.

## Roadmap

Planned work is tracked in [`docs/roadmap.md`](docs/roadmap.md).
