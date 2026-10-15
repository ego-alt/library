# Migrating an Existing Deployment

## October 2026: audit fixes (`audit-fixes` branch)

Upgrade steps:

1. Pull, then **rebuild the image**. `pillow` is a new dependency (cover
   thumbnails), so a bare `up -d` won't work.
   ```bash
   docker compose build library && docker compose up -d library
   ```
2. **Run the migrations** (automatic behind the dashboard: the library
   container now runs `flask db upgrade` on start). `b7e2c9d4f1a3` adds
   `books.deleted_at` (the trash).
   `a1b2c3d4e5f6` now skips dropping `users.email` when the column is already
   gone, so databases created without it upgrade cleanly.
   ```bash
   uv run flask db upgrade
   ```
3. Optional: set `TRASH_RETENTION_DAYS` (default 30). The trash also empties
   itself on every delete, so a `flask purge-trash` cron job isn't required.

New directories the app creates (all rebuildable, safe to delete):
`instance/thumbs/`, `instance/cache/`, `BOOK_DIR/.incoming/`.

API changes, for anything scripting against the app:
- Removed `/define_word` and `/translate_text`; use `POST /explain`
  `{text, context}` → `{explanation}`. All AI endpoints now require sign-in.
- `/load_more` takes `q` (search) and `view=all|unread|reading|finished`.
  The `title`/`author`/`genre`/`tags` params and `view=mine` are gone.
- `POST /book_metadata`: reading status goes in `status`, not in `tags`;
  title, author and genre are only changed for admins.
- `/upload_book` returns an `upload_id` (the file is staged, not yet in the
  library); confirm with `POST /upload_book_metadata {upload_id, title,
  author, genre, tags}`, or discard with `DELETE /upload_book/<upload_id>`.
- `DELETE /book/<filename>` moves the book to the trash;
  `POST /book/<filename>/restore` undoes it.
- `/bookmark` returns 401 when signed out (was 200).
- `/tags` no longer includes reading statuses.

## May 2026: library package reorganization

These steps move an existing deployment (old `instance/library.db`, books at
`/mnt/backup/books`) onto the new layout introduced in commit `9b85716`
(`large/reorganize source into library package`).

### What changed

- Source moved into a `library/` package; `app.py` is now a thin shim that
  re-exports `create_app`.
- Default `BOOK_DIR` is now `./books` instead of `/mnt/backup/books/`.
- Alembic migrations are now wired in. The schema baseline is captured by
  `migrations/versions/717c2541940c_initial_schema.py`.
- Models dropped the unused `User.email` column and added
  `ondelete="CASCADE"` to the `book_tags` foreign keys. **Existing databases
  are not changed by these edits**; only freshly-created ones reflect the new
  shape.

### What stayed the same

- `instance/library.db` resolves to the same absolute path on disk.
  `BASE_DIR` was updated so that even though `config.py` lives inside
  `library/` now, it still resolves to the project root.
- `docker-compose.yml` still mounts `${BOOK_DIR}:/mnt/backup/books`, so
  containerized runs are unaffected as long as `BOOK_DIR` is set in `.env`.

### Steps on the existing host

1. **Pull the new code.**

2. **Confirm `BOOK_DIR` is set.** Bare-metal `flask run` / `gunicorn` will
   otherwise fall back to `./books`. Add to `.env` if missing:

   ```
   BOOK_DIR=/mnt/backup/books
   ```

3. **Back up the database.**

   ```bash
   cp instance/library.db instance/library.db.bak
   ```

4. **Stamp the existing DB at the initial migration** so Alembic knows the
   schema is already in place and skips the table-creation migration:

   ```bash
   FLASK_APP=app.py flask db stamp 717c2541940c
   ```

5. **Boot as usual.** `flask run` / `docker compose up` work without further
   changes.

### The orphaned `email` column

Existing DBs kept a `users.email` column the model no longer uses. This is now
handled by migration `a1b2c3d4e5f6`, which drops it when present (and does
nothing on databases that never had it), so `flask db upgrade` is all you need.
Don't autogenerate a separate migration for it.

### Optional: add cascade FKs to `book_tags`

The `book_tags` join table on existing DBs still has FKs without
`ON DELETE CASCADE`. Autogenerate does **not** detect FK action changes, so
this needs a hand-written migration:

```bash
FLASK_APP=app.py flask db revision -m "cascade book_tags fks"
```

Then edit the generated file to use `op.batch_alter_table("book_tags", ...)`
to drop and recreate each FK with `ondelete="CASCADE"`. This is optional:
purging a book from the trash (`flask purge-trash`, or automatically after
30 days) clears its `book_tags` rows explicitly, and ORM-level cascades on
`User.bookmarks` and `Book.bookmarks` cover the rest.

### Quick recap

```bash
# on the existing host, after pulling
echo 'BOOK_DIR=/mnt/backup/books' >> .env       # if not already there
cp instance/library.db instance/library.db.bak
FLASK_APP=app.py flask db stamp 717c2541940c
FLASK_APP=app.py flask db upgrade               # later revisions (see above)
# done
```
