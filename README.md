# Shelves

A self-hosted EPUB library and reader. It runs on its own or behind the home stack's [dashboard](../dashboard), which handles sign-in.

## Features

### Library

- Cover gallery with title, author and reading progress; a bookshelf view of spines is also available.
- Search across titles, authors, genres and tags; filter by *Unread*, *Reading* or *Finished*.
- Add EPUBs by upload or drag and drop; edit details and covers, tag books, mark them private.
- Deleted books go to a 30-day trash with **Undo**.
- Day and night themes.

![The library by day](images/shelves-2026-10.png)

### Reader

- Continuous scroll or two-page spreads, with no toolbars while reading.
- Reading settings for text size, line spacing, column width, theme (Day, Sepia, Night, Black) and layout.
- Time left in the chapter and the book, based on your reading speed.
- Footnotes open in a pop-up beside their marker.
- **Ask and Explain**: select text to ask about it or get a definition or translation (needs `ANTHROPIC_API_KEY`).
- Reading position syncs across devices.

![The reader, with a footnote open](images/reader-2026-10.png)

### Phones and offline

- Touch layout, installable as an app; the last 12 books opened stay readable offline.
- Keyboard shortcuts on desktop; press `?` in the reader for the list.

![On a phone](images/phone-2026-10.png)

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
