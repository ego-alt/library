# Migrating an Existing Deployment

These steps move an existing deployment (old `instance/library.db`, books at
`/mnt/backup/books`) onto the new layout introduced in commit `9b85716`
(`large/reorganize source into library package`).

## What changed

- Source moved into a `library/` package; `app.py` is now a thin shim that
  re-exports `create_app`.
- Default `BOOK_DIR` is now `./books` instead of `/mnt/backup/books/`.
- Alembic migrations are now wired in. The schema baseline is captured by
  `migrations/versions/717c2541940c_initial_schema.py`.
- Models dropped the unused `User.email` column and added
  `ondelete="CASCADE"` to the `book_tags` foreign keys. **Existing databases
  are not changed by these edits**; only freshly-created ones reflect the new
  shape.

## What stayed the same

- `instance/library.db` resolves to the same absolute path on disk.
  `BASE_DIR` was updated so that even though `config.py` lives inside
  `library/` now, it still resolves to the project root.
- `docker-compose.yml` still mounts `${BOOK_DIR}:/mnt/backup/books`, so
  containerized runs are unaffected as long as `BOOK_DIR` is set in `.env`.

## Steps on the existing host

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

## Optional: clean up the orphaned `email` column

Your existing DB will retain the `users.email` column even though the model
no longer references it. SQLAlchemy ignores extra columns, so this is
harmless. If you want a tidy schema:

```bash
FLASK_APP=app.py flask db migrate -m "drop email column"
FLASK_APP=app.py flask db upgrade
```

Autogenerate catches column removals; this produces a migration that drops
`users.email` cleanly.

## Optional: add cascade FKs to `book_tags`

The `book_tags` join table on existing DBs still has FKs without
`ON DELETE CASCADE`. Autogenerate does **not** detect FK action changes, so
this needs a hand-written migration:

```bash
FLASK_APP=app.py flask db revision -m "cascade book_tags fks"
```

Then edit the generated file to use `op.batch_alter_table("book_tags", ...)`
to drop and recreate each FK with `ondelete="CASCADE"`. Skip this unless you
actually delete `Book` or `Tag` rows — ORM-level cascades on
`User.bookmarks` and `Book.bookmarks` already cover the common case.

## Quick recap

```bash
# on the existing host, after pulling
echo 'BOOK_DIR=/mnt/backup/books' >> .env       # if not already there
cp instance/library.db instance/library.db.bak
FLASK_APP=app.py flask db stamp 717c2541940c
# done
```
