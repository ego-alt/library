# Library — pre-launch product audit

Audited 2026-10-11 against `master` @ `b4c03d3`. I read all of the app code and ran it
locally with the five books in `books/`. I tested it as an admin, a standard user and
a signed-out visitor. The mobile checks were done at 375×667 in a desktop browser.
Touch-only behaviour (`hover: none`, swipes, the iOS keyboard) comes from reading the
code, not from a real phone. Mark those findings **[code]**.

The shelf view, the soft-academia light theme, the Gruvbox night theme and the
icon-led chrome are treated as intentional throughout. Nothing below asks to make
the app look more "standard".

Each finding uses the same layout:

> **What** — the problem · **Where** — the file or screen · **Why** — why it matters · **Fix** — the suggested fix

## Implementation status (updated 15 Oct 2026)

Each finding below now ends with a **Status** line. Every one is done except:
- **1.2** (genre merged into tags): partly done. It's a data migration, so it's your call.
- **2.4 / 8.3** (self-hosting): partly done. Bootstrap is removed, but Font Awesome, jQuery and Inter still come from CDNs. Self-hosting them means downloading vendor files into the repo, which needs your OK.

**How it was checked:**
- Every fix was verified in Chrome (headless, through Playwright) at 1280×800 and as a 375×667 touch phone, in light and dark where it mattered.
- Offline behaviour was tested with the network switched off.
- The test suite went from 139 passing (1 file not loading) to 189 passing, with nothing skipped.

**Bugs found while fixing (not in the original audit):**
- Every toast in the app was invisible: Bootstrap's `.toast:not(.show) { display: none }` hid them, error messages included.
- A book with several tags could be listed twice in the library.
- EPUB 2 books (NCX table of contents only) were rejected on upload as having "no table of contents".
- In night mode, chapter text outside `<p>` tags was near-black on charcoal.
- The cover's Details button was unreachable by keyboard, and the cover link had no size, so no focus ring.

**Before deploying:**
- **Migration:** run `flask db upgrade`. The new revision `b7e2c9d4f1a3` adds `books.deleted_at` for the trash; `a1b2c3d4e5f6` is now safe on databases without `users.email`.
- **Docker image:** rebuild it, because `pillow` is a new dependency (cover thumbnails).
- **New disk paths, all safe to delete:** `instance/thumbs/` and `instance/cache/`, plus `BOOK_DIR/.incoming/` for uploads awaiting confirmation.
- **Optional cron:** `flask purge-trash` empties the 30-day trash (it also runs on every delete).

**API behaviour that changed:**
- `/bookmark` returns 401 when signed out (was 200).
- The AI endpoints require sign-in.
- `POST /book_metadata` ignores title, author and genre from non-admins.
- `/upload_book` returns an `upload_id` instead of a filename.
- `/tags` no longer lists reading statuses.
- `view=mine` is still accepted (it now means "reading").

---

## 1. Core purpose

The app's job is to **catalogue, display and read my ebooks, anywhere**. Most of it
serves that. These parts don't, or they compete with each other.

**1.1 Three overlapping ways to say "what am I reading"**
- **What:** Reading state is shown three ways. The bookmark toggle in the header switches to "My books". The filter panel has *Unread / In Progress / Finished* tags. The details panel has the same statuses mixed in with custom tags.
- **Where:** `index.html` `#viewToggle`; `main.js` `applyFilters`; `metadata.py` `PROGRESS_TAG_VALUES`
- **Why:** You have to learn three controls for one idea. Progress states posing as tags are confusing: you can type "Finished" as a tag, and removing that chip quietly resets the book's reading status.
- **Fix:** Merge them into one status control. Replace the bookmark toggle with a small segmented control (*All · Reading · Finished*) at the top of the library. Remove the status values from the tag input completely, and keep tags for your own labels only.
- **Status:** Done. The bookmark toggle and four-field filter drawer are gone. The library now has one search box (each word must match title, author, genre or one of your tags) and an *All · Unread · Reading · Finished* control, remembered per device; the old `view=mine` links still work. Status is no longer a tag: the details panel has its own *Unread · Reading · Finished* control, `/tags` suggests only your own tags, and old clients that send status inside tags are still honoured. Per-view empty states ("Nothing on the go", "Nothing finished yet"…). Also fixed: a book with several tags could be listed twice. Verified in Chrome; tests added.

**1.2 Genre is a second, weaker tag system**
- **What:** Genre is one free-text string with its own filter field. Tags are many and per-user.
- **Where:** details panel; filter sidebar
- **Why:** It's two places to file the same kind of information, and genre can only hold one value.
- **Fix:** Fold genre into tags. If you want the EPUB's `dc:subject` on import, turn it into tags.
- **Status:** Partly done. Search now matches genre alongside title, author and tags, so the separate genre filter is gone. Genre is still its own single field in the details panel; merging it into tags is a data migration, and I'd rather you decide that one.

**1.3 Download takes a prime spot on every cover**
- **What:** Each cover has a download button. On touch devices it's always visible over the artwork.
- **Where:** `getBookTemplate` / `index.html` `.book-buttons`
- **Why:** Download is rare in a library whose whole point is reading in the browser. Two permanent white circles on every cover dilute the art, which is the main visual identity.
- **Fix:** Move Download into the details panel. Leave one discreet "…" on the cover (see 7.3).
- **Status:** Done. Covers now carry a single "…" (Details) button; **Download** moved into the details panel footer (icon-only in the phone sheet). Long-press is covered in 7.3.

**1.4 The upload form shows a "Filename" field**
- **What:** The confirm-upload panel shows an editable monospace filename.
- **Where:** `generateMetadataHtml(isUpload)`
- **Why:** Filenames are a storage detail. Editing one is also the riskiest input in the app (see 4.6).
- **Fix:** Remove it and always generate the filename from title and author.
- **Status:** Done. The filename field is gone; the server generates the name from the (edited) title and author when you confirm. The review panel now has a Tags field instead.

**1.5 Batch upload is advertised but not built**
- **What:** The README promises "drag and drop multiple files". The upload code only takes `files[0]` and there is no drop zone.
- **Where:** `README.md`; `handleFileUpload`
- **Why:** For a personal library, the first thing you do is import a whole folder.
- **Fix:** Either build it (a drop target on the page plus a per-file queue, see 5.2) or delete the README line. Keep `flask import-books` as the bulk path in the meantime.
- **Status:** Done. The file picker accepts several EPUBs at once, and you can drop EPUBs anywhere on the library page (a dashed drop target appears). Several files are added straight away using each EPUB's own metadata, with a running toast ("Adding 3 books… (2 of 3)") and a summary ("Added 2 books." plus any failures by name). A single file still opens the review panel. Verified in Chrome with two test EPUBs.

**1.6 AI aids: keep them, but make them earn their place**
- **What:** The three AI actions (Ask, Define, Translate) are unlabeled glyphs (?, book, language). Define and Translate are nearly the same job.
- **Where:** `reader.js` selection menu
- **Why:** You asked for simple AI that improves reading. Three icons you have to guess at is not simple.
- **Fix:** Merge them into one "Explain" action. Its prompt should define a single word, translate foreign text, or gloss a passage depending on what's selected. Keep Ask as the second action. Give both text labels.
- **Status:** Done. The selection menu is now two labelled buttons, **Ask** and **Explain**, and shows on desktop too (it used to be touch-only; mouse users could only reach the AI through shortcuts). Explain is one call (`POST /explain`) whose prompt defines a single word, translates foreign text, or glosses a passage, depending on the selection; after an answer the box offers "Ask a follow-up…". Shortcuts: **A** ask, **E** explain (the old **D**/**L** still work). The old `/define_word` and `/translate_text` endpoints remain for compatibility. Verified in Chrome on desktop and phone, with a stubbed answer because there's no API key here.

**1.7 Keep the access-level control, but keep it quiet**
- **What:** The "Admin only" checkbox and lock badge are a household feature.
- **Why:** It's fine to have, but it doesn't belong in the main reading flow.
- **Fix:** No change to the feature. Only the wording needs work (see 6).
- **Status:** Done. Kept the feature; the wording is now "Private — only admins can see this book" and the lock badge reads "Private".

---

## 2. Missing states

**2.1 A brand-new library is a blank page** *(bug)*
- **What:** With zero books, the server renders no covers. `offset` starts at 8, so the first client fetch asks for `/load_more/8`. That returns `[]` with `offset !== 0`, so `renderEmptyState()` never runs.
- **Where:** `main.js:1`, `loadMoreImages`
- **Why:** On first launch you see a header and nothing else.
- **Fix:** On first load, if `totalBooks === 0`, render a real empty state with the upload action in it: *"Your shelves are empty. Add an EPUB to begin."* plus an **Add a book** button.
- **Status:** Done. A library with no books shows "Your shelves are empty · Add an EPUB to begin." with an **Add a book** button (signed out: "Sign in to add books."), and the search toolbar is hidden until there's something to search. Verified against a throwaway empty library in Chrome. Browser visits to a missing or private book now get a readable page ("This book isn't in the library" + Back to library) instead of raw JSON; API calls still get JSON. Tests added.

**2.2 A book without a cover shows a broken image**
- **What:** If `read_epub_cover` finds no cover, it raises. `/cover/...` then returns a 500 and the grid shows the browser's broken-image icon with `alt="cover"`.
- **Where:** `index.py` `cover()`; `utils.read_epub_cover`
- **Why:** Plenty of EPUBs, especially self-made ones, have no cover. Covers are the only way to identify a book in the grid, so this book becomes unidentifiable.
- **Fix:** Generate a typographic fallback cover (title and author on a theme-coloured card, SVG is fine) on the server, and serve it with a 200. It suits the soft-academia look.
- **Status:** Done. A book with no usable cover gets a generated SVG: title and author set in a serif on a cloth-coloured board, with the colour picked from the title so it stays stable. Served with a 200. Tests added.

**2.3 The reader can spin forever**
- **What:** If `/load_book` returns a 403/404 JSON body, or the stream yields `{"type":"error"}`, the reader's `switch` has no case for it. The spinner stays up indefinitely.
- **Where:** `reader.js` `processChunk`
- **Why:** A missing or corrupt file looks the same as a slow network.
- **Fix:** Check `response.ok`, handle `type: "error"`, and show a calm error card: *"This book couldn't be opened."* with **Back to library** and **Try again** buttons.
- **Status:** Done. The reader handles a non-OK response, a stream error, and a failed fetch with a message plus **Back to library** / **Try again**. Offline, a never-opened book gets its own page instead of a spinner. Verified in Chrome.

**2.4 No offline story for an on-the-go reader**
- **What:** There's no service worker, no manifest and no cached chapters. Bootstrap, Font Awesome, jQuery and Inter all load from three CDNs.
- **Where:** both templates
- **Why:** On a train, opening the app shows nothing. If the CDNs are blocked or slow, every icon disappears, and the UI is almost entirely icons. If jQuery doesn't load, the library page doesn't work at all.
- **Fix:** (a) Self-host the four dependencies. (b) Add a manifest and a service worker that cache the app shell, plus the last N opened books' NDJSON in Cache Storage. (c) Show a small "Offline — showing downloaded books" banner.
- **Status:** Mostly done. A service worker caches the app shell, CDN assets, the last 12 opened books (data + images) and covers (capped at 400). An offline banner shows, and books not saved on this device are dimmed and explain themselves when tapped. Offline is detected by pinging the server, because `navigator.onLine` stays true on dead Wi-Fi. Verified offline in Chrome. Bootstrap is no longer loaded at all (8.3). **Not done:** self-hosting Font Awesome, jQuery and Inter. That means downloading vendor files into the repo, which needs your OK. Until then they're cached after the first visit.

**2.5 Bookmark saves fail silently**
- **What:** `saveBookmark` errors only go to `console.error`. When signed out, `/bookmark` returns **200** with "Authentication required.", so the client thinks the save worked.
- **Where:** `reader.js` `saveBookmark`; `reader.py` `bookmark()`
- **Why:** If your session expired, you lose your place without any warning.
- **Fix:** Return 401. On failure, show a small "Position not saved" dot in the bottom bar, keep the position in `localStorage`, and retry.
- **Status:** Done. Signed out, `/bookmark` returns 401 ("Sign in to save your place across devices.") and the reader keeps the position on this device only, without network noise. Signed in, positions are stored locally first and resent until the server confirms (see 4.8 for leaving the page). There's no visible "not saved" dot; the local copy makes one unnecessary in practice.

**2.6 Long titles get cut off in the edit panel**
- **What:** The title is a single-line `<input>`. On a phone, "The Jakarta Method: Washington's Anticommunist Crusade…" shows as "The Jakarta Method: Wash" (1,098px of text in a 267px box).
- **Where:** details panel, `.meta-title-input`
- **Why:** You can't see or check the title you're editing.
- **Fix:** Use an auto-growing `<textarea rows=1>` styled like the heading, or a `contenteditable` heading.
- **Status:** Done. The title is an auto-growing textarea (Enter still saves), so long titles wrap. Verified with *The Jakarta Method…*: five lines, fully visible.

**2.7 Missing author**
- **What:** If the EPUB has no author, the reader's TOC header shows "by " followed by nothing. The library cards never show text, so you can't tell.
- **Fix:** Display "Unknown author", and make the upload panel highlight the empty field.
- **Status:** Done. A missing author shows as "Unknown author" everywhere (reader contents panel, details, labels, fallback covers); the reader no longer prints a bare "by ". Uploads with no author are saved as "Unknown author".

**2.8 Author names are inconsistent**
- **What:** The data mixes "Judt, Tony" and "Bevins, Vincent" with "Walter Isaacson". The raw value shows in the reader ("by Judt, Tony") and in the details panel.
- **Fix:** Store authors as given, but display "First Last". Store a separate sort key for ordering by author.
- **Status:** Done. Display only (stored values are untouched): a single "Last, First" shows as "First Last" in the grid labels, Continue reading, details panel, reader and fallback covers. Several authors, suffixes like "Jr." and other shapes are left as stored. Admins editing see the stored value. There's no author sort in the app yet, so no sort key was needed. Tests added.

**2.9 Large collections**
- **What:** The page size is 8 books, which is two rows at desktop width. That means a new request every couple of scrolls, each also running a `COUNT` query. Spine width calls `epub_text_size`, which unzips every book on first view, and the cache is in-process `SimpleCache` that's lost on every restart or deploy.
- **Where:** `index.py` `BOOKS_PER_LOAD`, `_book_text_size`
- **Why:** At around 1,000 books, the first visit after a deploy is slow and the scroll stutters.
- **Fix:** Load 32–48 per page. Store `text_size` (and a cover thumbnail, see 8.2) as columns at import time.
- **Status:** Done, differently from the suggestion. Pages are 24 books (was 8), the client advances by the number actually returned, and the duplicate-row join that inflated counts is gone (1.1). Instead of new columns, the app cache moved from per-process memory to disk (`instance/cache/`, 5,000 entries), so cover bytes and per-book sizes survive restarts and deploys; thumbnails were already on disk (8.2). Measured: reading a book's sizes uncached costs about 7 ms, so even a 1,000-book library pays that once, not on every restart. Paging tested with 30 books.

**2.10 No sense of progress through the whole book**
- **What:** The reader shows "Section 12 of 44 · 1/94". Sections are EPUB spine items and include title pages and copyright pages.
- **Why:** That number means nothing to a reader.
- **Fix:** See 6.
- **Status:** Done. The reader label now reads *I - The Legacy of War · 14%*: the chapter name from the table of contents, plus whole-book progress. Chapters are weighted by size, using the same formula on the server (`utils.book_progress`) and in the reader, so the library and reader agree. The section count moved to the tooltip.

---

## 3. Inconsistency within the app

**3.1 Four button styles for one job**
- **Where:** `index.css` / `reader.css`
- **What:** The primary actions all look different:
  - `.save-button`: dark fill, `--text-sm`
  - `.login-submit`: dark fill, `--text-lg`, full width
  - `.btn-primary`: the accent fill, used nowhere visible now
  - reader `.controls .btn`: outlined, accent text, 24px tall
- **Fix:** Pick one primary style (the dark-ink fill suits the theme) and use the `.btn` primitives from `structural.css` everywhere. Delete the per-class duplicates.
- **Status:** Done. One primary style app-wide (`.btn-primary`): dark ink on paper by day, parchment on charcoal at night, 14px semibold. It's used by Save, Add to library, Sign in and the empty-state button; the duplicate `.save-button`/`.login-submit` styling is gone. Reader controls use the shared secondary style. The shared `structural.css` is untouched (it's meant to stay identical across the stack); the override lives in `index.css`.

**3.2 Two close buttons**
- **What:** `.close-metadata` is 32px, muted, rotates on hover and sits 12px from the edge. `.close-login` is 30px, primary colour, doesn't rotate and sits 16px from the edge.
- **Fix:** Make one `.btn-close` class.
- **Status:** Done. The details and sign-in panels share one close-button rule (32px, muted, same inset and hover).

**3.3 Field labels are styled two ways**
- **What:** Filter labels are bold sentence case ("Title"). Details-panel labels are uppercase with letter-spacing ("GENRE", "CUSTOM TAGS").
- **Fix:** Pick one. The uppercase small-caps style fits the academic feel, so use it everywhere.
- **Status:** Done. Every field label uses the small uppercase style, sign-in included (the filter-drawer labels went away with the drawer).

**3.4 Corner radii vary**
- **What:** Filter inputs use `--radius-sm`. Details inputs and the tag box use `--radius-md`. Login inputs use `--radius-md`.
- **Fix:** Inputs use `--radius-sm` everywhere, as `structural.css` already says.
- **Status:** Done. Inputs use `--radius-sm` throughout (details, tags, sign-in). The library search box stays a pill on purpose, so it reads as search rather than a form field.

**3.5 Breakpoints vary**
- **What:** The code uses 575.98px, 600px and 768px. `structural.css` says 640px is the single breakpoint for the stack.
- **Fix:** Use 640px.
- **Status:** Done. Every app media query uses 640px (the AI box widening uses ≥641px). Bootstrap's own grid breakpoints are untouched.

**3.6 Status chips ignore dark mode**
- **What:** `.started-tag`, `.finished-tag` and `.unread-tag` use pastel fills with `color: black`. They're the only light-on-dark elements in Gruvbox mode.
- **Fix:** Use Gruvbox equivalents (`#d65d0e`, `#98971a`, `#458588`) at about 30% opacity, with fg text.
- **Status:** Retired. Statuses aren't shown as tag chips any more (see 1.1), so the pastel status colours and their CSS were removed. The new status control uses theme tokens and works in both themes.

**3.7 Dates**
- **What:** "Added 2026-05-10" is a raw ISO date taken from a UTC timestamp, so it can be off by a day.
- **Fix:** Format it in the viewer's locale: "Added 10 May 2026".
- **Status:** Done. Shows as "Added 10 May 2026" in the viewer's locale, converted from UTC.

**3.8 Feedback appears in different places**
- **What:** Saving metadata confirms by changing the button text ("Saved!"). Upload confirms on the button and then reloads the page. Delete shows nothing. Errors appear as toasts.
- **Fix:** Use toasts for every outcome (see 4.1 for undo). Button text should only change while something is in progress.
- **Status:** Done. Outcomes are toasts everywhere: *Saved*, *Added "…"*, *Deleted "…" · Undo*, *Restored "…"*, errors. Buttons only change text while working ("Saving…", "Adding…", "Deleting…").

**3.9 The dark-mode icon turns into a filled circle**
- **What:** `fa-moon` changes to `fa-circle`.
- **Why:** A circle doesn't suggest "light mode".
- **Fix:** Use `fa-sun`.
- **Status:** Done. Night mode shows a moon; once on, it shows a sun, and the button's label switches between "Night mode" and "Day mode".

**3.10 Hard-coded colours outside the tokens**
- **What:** The highlight colours are set in JS (`reader.js:222`). The temp highlight, the cover-change scrim (`rgba(0,0,0,.55)`) and the wood colours are literals.
- **Fix:** Move them into `tokens.css` so the two themes stay consistent.
- **Status:** Done. The selection/highlight colour, image scrim and shelf wood are theme tokens in `tokens.css` with night variants; the JS-set highlight colours and per-rule dark overrides were removed.

**3.11 Loading text varies**
- **What:** Ask animates "Thinking." to "Thinking.........." (ten dots). Define says "Looking up definition...". Translate says "Translating...". The reader says "Loading book...". Uploads show nothing.
- **Fix:** Use one quiet pattern, such as a three-dot pulse or the word with an animated ellipsis, everywhere.
- **Status:** Done. Text loading states share one pattern (word + animated ellipsis: "Thinking", "Looking it up", "Translating"; "Reading Postwar.epub…" for uploads), and the reader's opening spinner is a quiet ring in the theme's muted ink with "Opening Postwar…".

---

## 4. Fragility

**4.1 Delete can't be undone**
- **What:** Delete calls native `confirm()` naming the filename slug ("Postwar__Judt_Tony.epub"), then removes the database row and the EPUB from disk.
- **Where:** `confirmDeleteBook`; `index.py` `delete_book`
- **Why:** A paid-quality app doesn't permanently delete a file on one click. The dialog also names a slug instead of the book.
- **Fix:** Soft delete: move the file to `BOOK_DIR/.trash/` and flag the row. Show a toast: *"Deleted Postwar. Undo"*. Purge the trash after 30 days (via `flask` command or cron). Then the confirm dialog can go.
- **Status:** Done. Delete now moves the book to a trash (`books.deleted_at`, new migration `b7e2c9d4f1a3`). The card disappears and a toast says *Deleted "Mao II" · Undo* (10 s). Undo calls `POST /book/<file>/restore`. Trashed books are hidden from every route. After 30 days (`TRASH_RETENTION_DAYS`) the row and EPUB are purged, either on the next delete or with `flask purge-trash`. The `confirm()` dialog is gone. Verified in Chrome; tests added.

**4.2 A cover picked for one book can be saved onto another** *(bug)*
- **What:** `handleCoverUpload` stores the chosen file in `window.newCoverFile`. If you close the panel without saving, then open a different book and click Save, `updateCover()` uploads the first book's cover to the second.
- **Where:** `main.js` `handleCoverUpload` / `saveMetadata`
- **Fix:** Clear `newCoverFile` whenever the panel opens or closes, and tie it to a filename.
- **Status:** Done. The pending cover is tied to its book's filename and cleared whenever the panel opens or closes. Verified: picking a cover for *Mao II*, closing, then saving *Postwar* sends no cover upload.

**4.3 Edited covers never refresh in the grid** *(bug)*
- **What:** `/cover/<file>` is served with `max-age=31536000`, and the grid URL has no version parameter. After a cover change, the grid keeps showing the old cover from browser cache, potentially for a year. The `?v=` cache-buster only reaches the details-panel preview.
- **Where:** `index.py` `cover()` and `get_covers()`
- **Fix:** Add `?v=<mtime>` to the cover URLs in `get_covers`, or switch to `no-cache` plus ETag. After saving, update the card in place.
- **Status:** Done. Every cover URL carries `?v=<file mtime>`, and after a cover change the new URL is swapped into the grid card, shelf spine and Continue reading card.

**4.4 Closing the details panel throws away edits silently**
- **What:** Esc, a click on the backdrop or the × discards title, genre, tag and cover changes without asking. A tag typed but not confirmed with Enter is dropped even when you click Save.
- **Fix:** Track a dirty flag. On close, ask *"Discard changes?"* using an inline bar, not `confirm()`. Include the pending tag text when saving.
- **Status:** Done. The details panel snapshots its fields when it opens. Closing with changes (fields, tags, status, a picked cover) or with an upload not yet added shows an inline bar: "You have unsaved changes · Keep editing · Discard changes". A typed but unconfirmed tag is included on Save. Verified in Chrome: a clean panel closes straight away, and a changed one asks and keeps or discards as chosen.

**4.5 Abandoned uploads leave orphan files**
- **What:** `/upload_book` writes the EPUB into `BOOK_DIR` under its final name before you confirm. If you then close the panel, the file stays on disk with no database row, and the next upload of the same book becomes `…_2.epub`.
- **Where:** `upload.py`
- **Fix:** Keep the file under `BOOK_DIR/.incoming/` until `upload_book_metadata` confirms. Clean up stale incoming files on startup.
- **Status:** Done. Uploads are staged in `BOOK_DIR/.incoming/<id>.epub` and only move into the library on confirm. Closing the review panel deletes the staged file (`DELETE /upload_book/<id>`), and unconfirmed uploads older than a day are swept on the next upload. Verified: cancel leaves nothing behind.

**4.6 The rename trusts a client-supplied filename**
- **What:** `upload_book_metadata` calls `os.rename(original, new)` with values straight from the request body. `../` in either value moves files outside `BOOK_DIR`. Any signed-in user can do this.
- **Fix:** Remove the client-side filename (1.4). If you keep it, run it through `secure_filename` and check the resolved path stays under `BOOK_DIR`.
- **Status:** Done. The client never sends a filename. The confirm call takes an upload id that must be 32 hex characters; `../`, unknown ids and non-strings are rejected (tested).

**4.7 Non-admins can rename books through the API**
- **What:** The UI only gives admins editable fields. The `POST /book_metadata` handler only checks that the user is signed in, then writes title, author and genre.
- **Fix:** Gate those three fields to admins on the server, the same way `access_level` already is.
- **Status:** Done. `POST /book_metadata` only changes title, author and genre for admins; everyone signed in can still set their own tags and status. New uploads record `uploaded_by`. Tests added.

**4.8 The last second of reading can be lost**
- **What:** Bookmark saves are throttled to once per second with plain `fetch`. Tapping back right after turning a page cancels the request.
- **Fix:** Also save on `pagehide` / `visibilitychange` with `navigator.sendBeacon`.
- **Status:** Done. On `pagehide` the reader stores the position locally and sends it with `navigator.sendBeacon`.

**4.9 Reading status changes on its own**
- **What:** Opening a book marks it *In Progress*, even if you only opened it to look. Reaching the last spine item marks it *Finished*, and the last item is often an index or notes. Nothing tells you either happened.
- **Fix:** Count a book as started only after real reading, such as a page turn or about 30 seconds. Count it as finished at 98% through the main text, or ask: *"Finished Postwar? · Mark as read"*.
- **Status:** Done. Opening a book no longer marks it started; saving a position past the opening (beyond 2% of the first section, or any later section) does. Instead of auto-marking *Finished* on the last section, the reader offers "Finished Mao II? · Mark as finished" once whole-book progress passes 90%. Status can be changed any time in the details panel.

**4.10 AI endpoints don't require sign-in**
- **What:** `/ask_question`, `/define_word` and `/translate_text` have no login check.
- **Why:** When standalone, anyone who can reach the app can spend your API credit. Behind the dashboard proxy this is less of a risk.
- **Fix:** Add `@json_login_required`.
- **Status:** Done. `/ask_question`, `/define_word` and `/translate_text` require sign-in (401 "Sign in to do that."). Tests added.

**4.11 Maintenance problems found while running the app**
- **What:**
  - Migration `a1b2c3d4e5f6` fails with `KeyError: 'email'` on a database that never had the column. That includes this machine's database; I stamped it to head to get the app running.
  - `tests/test_commands.py` won't import, because `BOOK_DIR_SENTINEL` no longer exists. The other 139 tests pass.
- **Fix:** Make the migration check for the column before dropping it, and fix the test import.
- **Status:** Done. Migration `a1b2c3d4e5f6` only drops `users.email` if the column exists, so it no longer fails on databases created without it (tested by upgrading a copy of this machine's pre-change database from the first revision: both migrations ran). `tests/test_commands.py` no longer imports the removed `BOOK_DIR_SENTINEL` (dropped upstream in `dbbc14c`), and gained a test for the new `purge-trash` command. The full suite now runs with no ignores.

---

## 5. Friction

### Most common task: continue my current book on my phone

| # | Step | Friction |
|---|------|----------|
| 1 | Open the library | The grid is sorted by *date added*, so the book you're reading isn't first. The only way to change that is the unlabeled bookmark icon, which is 20×24px. |
| 2 | Find the book | Covers only, with no title text. That's fine for 20 books but a scanning chore for 500. Broken covers (2.2) are unfindable. |
| 3 | Tap the cover | Full page navigation, then a spinner. The whole book streams in again every time (3 MB for *Postwar*, 1.5 s on localhost; see 8.1). |
| 4 | Land in the book | Good: it opens at the right chapter and position. But the bars cover the first lines and the label reads "Section 12 of 44". |
| 5 | Read | In scroll mode, a slightly diagonal swipe of 70px or more jumps a whole section (`reader.js:829`). That's easy to trigger by accident while scrolling. |
| 6 | Go back to the library | The library reloads from scratch: scroll position, filters and layout fetch state are all lost. |

**Fixes:**
- Add a **"Continue reading" row** at the top of the library: the last one to three books opened, each with a thin progress line and a % figure. One tap from launch to the page you left. This is the single biggest improvement to the app's feel.
- Disable swipe-to-change-section in scroll mode. Keep swipe for page turns in paginated mode.
- Keep library state when you go back. Cache `loadedBooks` and the scroll position in `sessionStorage`.

### Second task: add a book

1. Tap the upload icon. Nothing tells you it means "add a book".
2. Pick a file. **No feedback at all** while it uploads and parses. A 20 MB EPUB on mobile means several seconds of silence.
3. The panel appears with a Filename field (1.4) and no Tags field. You have to add tags in a second pass.
4. "Add to library" reloads the whole page, and the new book appears at the top with no highlight.

**Fix:** Show a progress toast (*"Adding Postwar…"*) as soon as a file is picked. Include tags in the upload panel. After confirming, add the card in place with a brief highlight instead of reloading.

### Third task: look up a word (phone) **[code]**

You select text. The custom menu appears 10px *below* the selection while iOS shows its own callout above it. Then you tap one of three unlabeled 36px icons. The answer appears in a 300px floating box positioned from the selection, which can run off the right edge at 375px.

**Fix:** On mobile, show the answer in a bottom sheet anchored to the bottom bar, not a floating box.

**Status (all three walkthroughs): done.**
- *Continue my book:* step 1 is now the Continue reading row (one tap to your place, with %), the label shows the chapter name and whole-book %, swipe only turns pages in paginated mode, and returning from the reader restores the library's search, loaded books and scroll position (same tab, within 30 minutes). Reopening a book is instant because it's cached (8.1).
- *Add a book:* a toast appears as soon as a file is picked, the review panel has Tags and no Filename, and the book appears in place with a highlight (no reload). Several files, or a drag-and-drop, add in one go (1.5). Bonus fix: EPUB 2 books with only an NCX table of contents used to be rejected as having "no table of contents"; they're accepted now.
- *Look up a word on a phone:* the answer is a bottom sheet above the keyboard (7.6), and the selection buttons are 44px.

---

## 6. Copy

| Where | Now | Suggested |
|---|---|---|
| Upload error (`upload.py:72`) | "Uploaded EPUB does not contain a table of contents. Quality is questionable." | "This book has no table of contents, so it can't be added. Re-exporting it from Calibre usually fixes this." |
| Upload error | "Invalid file format. Please upload an EPUB file" | "Only .epub files can be added." |
| Upload error | "Failed to process EPUB file: " + Python exception | "Couldn't read this file — it may be damaged." (log the exception, don't show it) |
| Upload (network) | "Error uploading file" | "Upload didn't finish. Check your connection and try again." |
| Save metadata | "Error saving metadata: INTERNAL SERVER ERROR" (jQuery `statusText`) | "Couldn't save your changes. Try again." |
| Save cover | "Error updating cover: …" | "Couldn't change the cover. Try a JPG or PNG." |
| Infinite scroll | "Could not load more books" | "Couldn't load more books." + **Retry** |
| Reader error | "Error loading book. Please try again." (Bootstrap red alert) | "This book couldn't be opened." + **Back to library** / **Try again** |
| AI error | "Sorry, an error occurred while getting the answer." | "Couldn't get an answer just now." If no API key is set: "AI help isn't set up." |
| AI loading | "Thinking.........." | "Thinking…" |
| Empty filter result | "No books match your filters / Try adjusting your search criteria" | "Nothing on the shelves matches." + **Clear filters** |
| Empty "mine" view | "Your library is empty / Open a book to start reading…" | "Nothing on the go. Books you open will appear here." (the library isn't empty) |
| Delete confirm | `Permanently delete "Postwar__Judt_Tony.epub"?` | Replace with undo toast: "Deleted *Postwar*. Undo" |
| Access toggle | "Admin only — hide from standard users" | "Private — only admins can see this" |
| Tags label | "CUSTOM TAGS" / placeholder "Type and press Enter" | "TAGS" / "Add a tag" |
| Reader position | "Section 12 of 44 · 1/94" | "The Legacy of War · 14%" (chapter title + whole-book %) |
| Login | "Login" heading and button; "An error occurred. Please try again." | "Sign in"; "Couldn't reach the library. Try again." |
| Cover alt text | `alt="cover"` | `alt="{title} by {author}"` |
| Tab title before load | "EPUB Reader" | The book title (it's known on the server, so render it into the template) |
| Icon buttons without labels | dark mode, upload, filter, login/logout, font −/+, back | Add `aria-label` and `title`: "Night mode", "Add a book", "Search & filter", "Sign out", "Smaller text", "Larger text", "Library" |


**Status: done**, with two retirements. Every row above has been rewritten as suggested; server errors no longer echo Python exceptions (those go to the log). Changes from the suggestions:
- **Delete confirm:** retired. There's no dialog any more; delete shows *Deleted "Mao II" · Undo* (4.1).
- **AI loading:** one pattern everywhere ("Thinking", "Looking it up", "Translating", each with an animated ellipsis). Errors show the server's plain message.

Also: every icon-only button has an `aria-label` (library and reader), and grid covers read "Read Postwar by Judt, Tony". A scan in Chrome found no unlabeled buttons on either page.

---

## 7. Mobile (375px)

**7.1 Header tap targets are 18–26px**
- **What:** Measured sizes: dark-mode 24×24, layout 18×24, view 20×24, login 26×24, upload 24×24, filter 24×24. The guideline is 44×44.
- **Where:** `index.css:704`, the phone media query shrinks them further
- **Fix:** Keep the glyphs small but give each button a 44×44 hit area (padding, no extra visual weight). With six icons at 375px wide, move the rare ones (night mode, sign out) into a single "⋯" menu.
- **Status:** Done. Header icons keep their size but get 44×44 hit areas. The header is down to four icons (night mode, layout, sign in/out, add a book), because search and status moved into the toolbar. Measured at 375px: no header control under 44px. The status buttons are 40px inside a padded control (about 46px total).

**7.2 The details panel opens the keyboard** **[code]**
- **What:** `focusFirstMetadataField()` focuses the title input every time an admin opens a book's details. On a phone the keyboard immediately covers half the panel. The Save button is already below the fold.
- **Fix:** Don't auto-focus on touch devices. On mobile, make the panel a bottom sheet with a sticky footer for Save and Delete. `--radius-lg` is already defined as the "mobile bottom-sheet" radius.
- **Status:** Done. On phones (≤640px) the details panel is a bottom sheet with the Delete/Save footer pinned to the bottom, padded for the home bar. Touch devices don't auto-focus the title, so the keyboard stays down until you tap a field. Verified at 375px: Save sits fully on screen and nothing is focused on open.

**7.3 In shelf view, touch users can't open details**
- **What:** Spine buttons only appear on hover, and the CSS comment says this is intended.
- **Why:** On a phone, shelf view can only open books. You can't see details, tags or download.
- **Fix:** Long-press a spine to open details. Make long-press do the same in the grid and drop the permanent cover buttons (1.3).
- **Status:** Done. Press and hold any cover, shelf spine or Continue reading card for half a second to open its details (with a tiny haptic tick where supported). The press doesn't also open the book, and iOS's link callout is suppressed on those elements. Verified in Chrome's touch emulation.

**7.4 iOS zooms in when you focus some inputs** **[code]**
- **What:** These inputs are 14px (`--text-sm`): `.meta-input` (genre, filename), `.meta-author-input` and the reader's AI `.search-input`. iOS Safari zooms the page when an input under 16px gets focus.
- **Fix:** Set inputs to 16px at the 640px breakpoint.
- **Status:** Done. On phones, author, genre, tags, login and the AI box are 16px. Measured at 375px: every input in the details sheet is ≥16px.

**7.5 Notch, home bar and the iOS toolbar** **[code]**
- **What:**
  - There's no `viewport-fit=cover` and no `env(safe-area-inset-*)`. The reader's fixed top bar (`top: 0`) and bottom bar (`bottom: 0`) will sit under the notch and home indicator in landscape and in a home-screen web app.
  - Paginated mode uses `height: 100vh`. On iOS Safari that's taller than the visible area, so the last lines of each page and the bottom bar hide behind the browser toolbar.
- **Fix:** Add `viewport-fit=cover`, pad the bars with `env(safe-area-inset-top/bottom)`, and use `100dvh` (falling back to `100vh`).
- **Status:** Done. `viewport-fit=cover` on both pages. Top and bottom reader bars, the TOC, the toast stack, the offline banner and the library container pad themselves with `env(safe-area-inset-*)`. Paginated mode uses `100dvh` (with a `100vh` fallback); measured: the page is exactly the visible height at 375×667.

**7.6 The keyboard covers the Ask box** **[code]**
- **What:** The Ask overlay is positioned below or above the selection *before* the keyboard opens. For a selection in the lower half of the screen, the keyboard then covers the input.
- **Fix:** On mobile, use a bottom-sheet Ask box that moves above the keyboard (`visualViewport` resize).
- **Status:** Done. On phones the Ask/Define/Translate box is a full-width bottom sheet that follows `visualViewport`, so it stays above the keyboard. Its input is 16px. Verified at 375px.

**7.7 Reader bar buttons are short**
- **What:** Prev/next section buttons are 75×24px. The top bar buttons are about 40×32px.
- **Fix:** Make them at least 44px tall.
- **Status:** Done. On touch or ≤640px, reader controls are at least 44×44, TOC rows are taller, and the selection menu buttons are 44px. Measured: no reader control under 44px. The chapter name truncates but the % never does.

**7.8 Screens that should change structure on mobile, not just shrink**
- **Filter sidebar:** a 300px drawer with four separate fields. On a phone, replace it with **one search field** at the top of the library (matching title, author and tag) plus status chips under it. The drawer can stay on desktop.
- **Details panel:** a bottom sheet (see 7.2).
- **TOC:** a 300px drawer that leaves a sliver of page visible. On a phone, make it full-screen with the current chapter scrolled into view and highlighted. It currently opens at the top every time, even when you're in chapter 30.
- **AI answer:** a bottom sheet (see 5).
- **Status:** Done. Details panel → bottom sheet (7.2), AI answer → bottom sheet (7.6), TOC → full screen on phones, opening at the current chapter. The filter drawer is replaced by the always-visible search box and status control, full-width on phones.

**7.9 It can't be installed as an app**
- **What:** There's no web manifest and no `apple-touch-icon`.
- **Why:** For a reader you carry around, opening it from the home screen with no browser chrome is most of what makes it feel native.
- **Fix:** Add a manifest with `display: standalone` and the theme colours.
- **Status:** Done. Added a web manifest (`/manifest.webmanifest`, standalone, theme colours), `apple-touch-icon` and theme-color meta. The new icons are book spines on a shelf, drawn in the app's palette (`static/icons/`).

---

## 8. Speed and feel

**8.1 Every book open downloads the whole book again**
- **What:** `/load_book` streams every chapter with no caching headers. That's 3.0 MB for *Postwar* and took 1.5 s on localhost; on 4G it's several seconds and real data.
- **Fix:** Cache the NDJSON in the browser keyed on the file's mtime (Cache Storage, which also gives offline, see 2.4). Or serve the first chapter immediately and fetch others on demand.
- **Status:** Done. `/load_book?v=<mtime>` is served cache-first by the service worker, so reopening a book costs no network. Least-recently-opened books are evicted after 12.

**8.2 Covers are served at full size**
- **What:** Grid covers come straight out of the EPUB at full resolution. *Elon Musk* is **2.3 MB** and *Postwar* is 0.7 MB, for a card about 170px wide. Shelf spines use the same image.
- **Fix:** Generate and cache a 400px-wide WebP thumbnail per book, and keep the original for the details panel.
- **Status:** Done. `/cover/<file>?w=120|400` serves cached WebP thumbnails (written to `instance/thumbs/`, old versions cleaned up). The grid and shelf use 400px and Continue reading uses 120px; the details panel keeps the full image. Measured: *Elon Musk* 2.31 MB → 36 KB, *Postwar* 717 KB → 57 KB. Covers Pillow can't decode (SVG, broken) are served as-is. Adds the `pillow` dependency, so rebuild the Docker image.

**8.3 Render-blocking dependencies from three CDNs**
- **What:** The page loads Bootstrap (~160 KB, used for a grid and a few utility classes), Font Awesome (all icons), jQuery and Google Fonts from separate CDNs.
- **Fix:** Self-host them. Replace Bootstrap's grid with about 10 lines of CSS grid. Subset the icons.
- **Status:** Partly done. **Bootstrap is gone:** the ~160 KB stylesheet and its CDN request are replaced by `static/css/base.css`, a few hundred lines covering only what the app used (reset, container, the three grid columns, a handful of utilities, spinner, alert), now in theme colours. Verified with before/after screenshots at desktop and 375px in both themes: library and details are pixel-identical. The reader changed in one intended way: body text uses the theme's reading colour, which fixed a night-mode bug where text outside `<p>` tags (chapter numbers, epigraphs) was near-black on charcoal and unreadable. **Still on CDNs:** Font Awesome, jQuery and Inter; self-hosting them means downloading vendor files into the repo, which I left for your OK. The service worker caches them after the first visit (2.4).

**8.4 No instant feedback**
- **What:**
  - Uploading shows nothing between picking a file and the panel appearing (5).
  - Filtering clears the grid before results arrive, so it flashes empty.
  - Saving tags doesn't update the visible card.
  - Toggling *My books* empties and refills the grid.
- **Fix:** Keep the current results visible, dimmed, until new ones arrive. Show an upload toast. Update cards in place.
- **Status:** Done. A pending-upload toast appears immediately. Searching or switching views keeps the current results (dimmed) until new ones arrive, and responses from an older search are ignored. Status and tag edits save in place, new books appear in place with a brief highlight, and cover changes update every copy of the cover.

**8.5 Keyboard shortcuts**
- **What:**
  - Reader: AI uses **⌘/Ctrl+D** and **⌘/Ctrl+L**, which take over the browser's own *Bookmark* and *Address bar* shortcuts. ⌘L is one people use all the time. The README says plain `D` / `L`, which is also wrong.
  - Library page: no shortcuts at all.
  - Esc closes the details panel, but not the filter drawer, the sign-in dialog or the TOC.
- **Fix:**
  - Reader: no modifier needed when text is selected: `A` ask, `E` explain/define. Also `T` table of contents, `+`/`−` text size, `N` night, `Esc` close anything or go back to the library.
  - Scroll mode: `←`/`→` turn by one screen, like paginated mode.
  - Library: `/` focus search, `U` add a book, `Esc` close any panel.
  - `?` shows a small shortcut sheet.
- **Status:** Done. Reader: with text selected, **A** asks, **D** defines, **L** translates. No modifier, so the browser's ⌘D and ⌘L work again (verified: ⌘L isn't intercepted). **T** contents, **+/−** text size, **N** night mode, **Esc** closes the AI box, TOC or help, **?** shows a shortcut sheet. In scroll mode ←/→ move a screen. Library: **/** focuses search, **U** adds a book, **Esc** closes the details panel or sign-in. README updated. Deviation: Esc doesn't leave the book, because that felt too easy to hit by accident; the back arrow does that.

**8.6 Focus handling in panels**
- **What:** The details and sign-in panels don't trap focus, so Tab moves behind them. Focus doesn't return to the cover you opened from when the panel closes.
- **Fix:** Use `<dialog>` with `showModal()`. It handles focus, Esc and the backdrop for you.
- **Status:** Done, without `<dialog>`. Swapping to `<dialog>` would mean reworking jQuery's fade animations, so I kept the existing overlays and added the behaviour: Tab cycles inside the open panel, focus moves into it on open (desktop) and returns to the button that opened it on close. Both overlays are labelled dialogs. The cover's Details button is now reachable by keyboard (it used to show on hover only); verified in Chrome: Tab from a cover lands on Details, Enter opens, 15 Tabs stay inside, Esc closes, and focus returns to Details.

---

## Top 10, ranked by how much better the app will feel

| Rank | Fix | Section | Size | Status |
|---|---|---|---|---|
| 1 | **"Continue reading" row** at the top of the library with whole-book % — one tap from launch to your page | 5, 2.10 | **Medium** | Done |
| 2 | **Cache books and covers, self-host dependencies, make it installable and usable offline** (manifest + service worker) | 8.1, 2.4, 7.9, 8.3 | **Large** | Mostly done (self-hosting pending your OK) |
| 3 | **Undo instead of permanent delete**; fix the cover-mix-up and stale-cover bugs | 4.1, 4.2, 4.3 | **Medium** | Done |
| 4 | **Mobile bottom sheets** for details, AI answers and the TOC; no auto-focus; sticky Save | 7.2, 7.6, 7.8 | **Medium** | Done |
| 5 | **Cover thumbnails and a typographic fallback cover** | 8.2, 2.2 | **Medium** | Done |
| 6 | **One reading-status control**, and status removed from tags (plus less eager auto-status) | 1.1, 4.9 | **Medium** | Done |
| 7 | **Safe areas, `100dvh`, 44px tap targets, 16px inputs** | 7.1, 7.4, 7.5, 7.7 | **Small** | Done |
| 8 | **Rewrite all user-facing copy**, labels and aria-labels on icon buttons, readable position label | 6 | **Small** | Done |
| 9 | **Real empty and error states** (first-run library, reader spinner, failed bookmark saves) | 2.1, 2.3, 2.5 | **Small** | Done |
| 10 | **Keyboard shortcuts that don't override the browser**, plus Esc closing every panel and `<dialog>` focus handling | 8.5, 8.6 | **Small** | Done (focus handled without `<dialog>`) |

Close runners-up: unify the button and label styles (3.1–3.4, small); disable
swipe-to-change-section in scroll mode (5, small); feedback while uploading (8.4,
small); server-side checks on metadata and rename (4.6, 4.7, small). **All done.**
