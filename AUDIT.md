# Shelves: audit of Comics, Get and Downloads (revised)

**Scope:** the comics shelf, series pages, the comic reader, Get, Downloads and the download half of Settings.

**The rule for this revision:** the books app (gallery, details panel, book reader) is the standard. A fix belongs here only if it:
- makes the new parts behave and look like the books app;
- fixes something broken or misleading; or
- removes something.

Anything that would add a screen, a sheet or a feature books doesn't have was cut (listed at the end).

**How it was checked:** I read the code on `comics` (= live `da66d9b`) and ran the app on demo data at 375×812 with touch emulation and at 1280 on desktop. Tap sizes are measured from the DOM.

---

## A. Unify with the books app

These carry the most weight. They make Comics, Get and Downloads feel like the same app as the gallery and the book reader.

**A1. The comic reader should be the book reader, with pages instead of text.**
- *Now:* `comic_reader.css` and `comic_reader.html` have a separate visual language:
  - always near-black, whatever day/night is set to;
  - a blue accent (`#8fb0cf`) and hard-coded browns (`#9a8e7a`, `#d9ccb2`);
  - its own `.cr-btn` buttons and a 1 / 2 / ↕ segmented control;
  - a ⇄ glyph and a Fit button;
  - bars that fade on a 2.5 s timer;
  - a blue "Next issue" button on a "The end." screen.
  The book reader has the `.top-controls` bar (☰ ← … Aa), the `Aa` sheet (`.reader-settings`, `.rs-row`, `.rs-seg`), the Day/Sepia/Night/Black themes tied to the app's night switch, a `reading-progress` line, the `?` sheet, "Opening *title*…" while loading, and the `chapter-end` "NEXT  Chapter 2 →" block.
- *Why:* Opening a comic feels like leaving the app.
- *Fix:* Build the comic reader from the book reader's parts:
  - **Bar:** `.top-controls` with ← (back to the series), the title "Starfall #12", and `Aa`. Same reveal rules as the book reader: hidden on open, a tap in the middle toggles, the pointer at the top edge shows it on desktop.
  - **`Aa` sheet:** the same `.rs-row`/`.rs-seg` rows for *Pages* (One · Two · Scroll), *Fit* (Height · Width), *Direction* (Left to right · Right to left) and *Theme*. Download goes in the sheet too. On phones this brings back the Fit control, which is hidden at ≤640px today.
  - **Theme:** the page background follows the reader theme (`--reader-bg`), defaulting to Night or Black when the app is in night mode, exactly like books.
  - **Progress:** the `reading-progress` line at the top, plus the page count in the running-foot position ("3 / 24"). The slider stays, but only while the chrome is showing.
  - **End of issue:** the `chapter-end` block, "NEXT  #13 →". At the end of the last issue, offer to mark it read, like `maybeOfferFinished`.
  - **Loading:** "Opening Starfall #12…" as in the book reader, and a quiet page-number placeholder while a page image loads.
  - **Keys:** add the `?` sheet with the same look. Esc closes the sheet or bars and never leaves the reader (today it navigates to the series). `N` toggles night, as in the book reader.
  - **Page turns:** the same slide the paginated book reader uses (`applyPageTransform`), off under reduced motion.

**A2. Covers carry no pills; state goes in the caption, like books.**
- *Now:* comic covers carry pills: "Reading", "Up next", "Wanted", "Downloading", "Out 1 Nov" on series pages, and "Get" / "Follow" / "Following" / "Requested" on Get. Book covers have none. Their state lives in the small-caps caption line ("MIRA OKAFOR · 42%").
- *Fix:* Remove the pills and put the state in the caption: "19 AUG · 50%", "READ", "WANTED", "DOWNLOADING", "OUT 1 NOV", "IN YOUR LIBRARY", "FOLLOWING". Missing issues keep their fade, which already says "not here". On Get, the whole cover is the action, as on the books shelf.

**A3. No ✓ toggle on issue covers.**
- *Now:* every issue cover has a ✓ button (shown permanently on touch, so 16 covers make 32 floating buttons with ⋯). Books mark status in one place, the details panel.
- *Fix:* Drop the ✓ button. "Mark as read / unread" is already in the issue's ⋯ menu. For readers, give them the same ⋯ menu (Read, Mark as read, Download) instead of ✓ plus a download button. Read state shows in the caption ("READ"), as finished books show 100%.

**A4. One filter control.**
- *Now:* the series page's All / Have / Missing filter is compact, left-aligned and 28 px tall ("All" is 21 px wide). The books and comics shelves use the evenly spread 40 px `status-filter`, and Get uses it stretched.
- *Fix:* Series uses exactly the shelf's `.status-filter` (`library-toolbar` layout) at the same size.

**A5. One menu, one way to confirm.**
- *Now:*
  - the series header uses `<details class="more">` with a literal "⋯" text character;
  - covers and rows use `openMenu` with the icon;
  - destructive actions use native `confirm()`: delete a comic file, Stop following (two chained dialogs, where the second's safe answer is *Cancel*), Import "Delete", Remove a book request.
  - The books app confirms inside its own UI: the details panel's `discard-bar` ("You have unsaved changes · Keep editing · Discard changes").
- *Fix:*
  - The series header ⋯ becomes the same icon button and `openMenu` as on covers.
  - Destructive actions confirm with the books' `discard-bar` pattern, inline where the action was: "Delete the file for #12? · Keep · Delete".
  - Stop following becomes one bar: "Stop following Starfall? · Keep the files · Delete the files too", with *Keep* focused.
  - No `confirm()` anywhere.

**A6. The series header should read like the book details panel.**
- *Now:* `.series-head` uses its own type: `--text-xl` title, a muted meta line, plain description, and then a row of [Continue #12] Get [All missing ▾] ⋯.
- *Fix:*
  - Use the details panel's header scale: `meta-title` 1.5rem/600 and the author line style for publisher · year.
  - Show "16 issues" as the panel's small-caps label/value style.
  - [Continue #12] is the one primary button, like *Save changes* in the panel.
  - "Get new issues / all missing / none" moves into the ⋯ menu as three items with the current one ticked (B4), so the header holds only reading.

**A7. Settings and Import use the details panel's form style.**
- *Now:*
  - Settings is frosted cards with shadows, `.field-grid` labels in sentence case, `.input` fields.
  - Import rows use `.input` and native selects.
  - The details panel uses small-caps labels (`meta-label`: STATUS, GENRE, TAGS) over full-width `meta-input` fields, with no cards.
- *Fix:*
  - Settings becomes sections on the page (title, one hint line, hairline separators), with `meta-label` / `meta-input` fields.
  - The Save bar matches the panel footer: Discard as a quiet text button, Save as the primary.
  - Import's series and number fields use the same field style.

**A8. Colours come from the tokens.**
- *Now:* `comics.css` has `#b07a1c` for Downloading. `comic_reader.css` hard-codes its whole palette (`#0b0a09`, `#eadfca`, `#9a8e7a`, `#d9ccb2`, `#8fb0cf`).
- *Fix:* Use `tokens.css` and the reader's `--reader-*` variables. With A1 and A2, most of these rules disappear.

**A9. Copy in the books' voice.**
- *Now:* Books say "Saved", "Added "X"", "Deleted "X"", "Couldn't save your changes. Try again." The new parts use scene-release names, developer phrasing and inconsistent verbs (Grab / Search now / Pick / Sent to SABnzbd).
- *Fix:* See section F. Use one verb set: *Download* (button), *Find now* (menu), "Downloading Starfall #13" (toast). Never show a release's file name in a toast.

**A10. Keyboard parity.**
- *Now:* the books shelf binds `/` to focus search; the comics shelf and Get don't.
- *Fix:*
  - `/` focuses search on Comics and Get.
  - The comic reader gets the `?` sheet and the Esc and `N` behaviour from A1.

**A11. Offline parity.**
- *Now:* books keep the last 12 opened offline, show "You're offline. Saved books still open.", dim covers that can't open with an explanatory toast, and queue the reading position locally. Comics have none of this: `sw.js` passes `comics/` straight through, so offline the Comics tab is the browser's error page, and `comic_reader.js` drops progress on a failed save (`.catch(() => {})`).
- *Fix:*
  - Give comics the same treatment, with no new controls: the last 12 opened issues' pages are kept (keyed on file size as books are keyed on mtime), comics pages are network-first cached, and the same banner, dimming and toast apply (`pwa.js`).
  - Queue progress in localStorage and resend it when back online, like `POSITION_KEY` in `reader.js`.
  - Separately, the service worker's install warms only `/`. It should precache the shell CSS, JS and fonts, so the first offline launch isn't unstyled (this affects books too).

**A12. Long issue walls load like the books shelf.**
- *Now:* a series page renders every issue, plus a JSON copy of all of them. A 600-issue run is heavy on a phone. The books shelf loads in batches with skeletons (`load_more`).
- *Fix:* Batch the issue wall the same way, starting around the up-next issue. Get's first search should show the shelf's `book-skeleton` covers too, instead of a lone "Looking…".

**A13. Small consistency items.**
- *Page titles:* the book reader's tab is the book's title; the comic reader's is "Starfall #12 · Shelves". Use "Starfall #12".
- *Downloads empty states:* "Nothing yet." lines become the shelf's `empty-state` style where a whole section is empty.
- *Dates:* one format throughout, the `comic_date` / `formatDate` rule (day and month, plus the year if it isn't this year). Spelled-out relative time only within a day ("2 hours ago", not "2 h ago" or "1 d ago").
- *Dates in Wanted:* book rows say "Asked 21 Oct" and comic rows say a bare "18 Oct" (the release date). Label both.

---

## B. Things that don't serve the purpose: remove or simplify

**B1. Background jobs on Downloads.**
- *Where:* `#jobs`: four Run buttons and "The worker hasn't checked in…".
- *Fix:* Remove the section. Show one line at the top of Downloads only when the worker is down or a job failed ("Downloads are paused."). Search now and Match again already cover the manual cases.

**B2. "Coming up" on Downloads.**
- *Fix:* Remove it. Release dates already show on the missing covers of each series page (as caption text after A2), and they're about reading, not downloading.

**B3. The Downloads badge.**
- *Now:* it counts active downloads *plus* files in the import folder ("5" while Downloading shows 3). The folder is listed from disk on every admin page load.
- *Fix:* Count downloads in progress only. Failures surface on the Downloads page (C3), not as a second indicator.

**B4. The monitor select next to Continue, and on Get.**
- *Now:* the series header reads "[Continue #12] Get [All missing ▾]". Get has a "Get: New issues" select in the comics section header, about 8 screens down on a phone, which silently decides what a tap on a series does.
- *Fix:* Remove both selects. Following from Get always starts with *New issues* (the safe default). The choice lives in the series ⋯ menu (A6). After following, you land on the series page, where it's one tap to change.

**B5. Admins and readers see different issue orders.**
- *Where:* `series_page`: `reversed(shown) if admin else shown`.
- *Fix:* Reading order (#1 first) for everyone. Admins use Have / Missing to manage.

---

## C. Fragility and truthfulness

**C1. Following a series blocks on ComicVine.**
- *Where:* `POST /comics/api/series` fetches every issue before answering: "Adding…" for seconds.
- *Fix:* Save the series and go straight to its page. Fetch the issues in the worker, with a "Fetching issues…" line where the wall will be.

**C2. A stalled download looks live, and client hiccups show as raw errors.**
- *Now:* "5% · 1 d ago" looks the same as a healthy download. `check_downloads` writes client exceptions into the row's error ("SABnzbd didn't answer (ConnectError).").
- *Fix:*
  - Call it "Stalled" after 6 hours without progress, and offer *Try another release* in its menu.
  - Report a client that isn't answering once, as the section hint ("SABnzbd isn't answering — check Settings"), not under each row.

**C3. Failures are hidden at the bottom.**
- *Now:* a failed download is only in the folded History, with raw reasons ("qBittorrent: stalledDL", "missingFiles").
- *Fix:* Failed downloads whose book or issue is still wanted show at the top of Downloading, in plain words ("Its files went missing from qBittorrent"), with *Try another release* / *Stop looking*. Once retried or stopped, they drop back into History.

**C4. Series search hides client failures.**
- *Where:* the series ⋯ "Search for wanted issues" uses `search_item`, which swallows `ClientError`. With SABnzbd down, it reports "Nothing new on the indexers".
- *Fix:* Report it: "Found 3, but SABnzbd isn't answering."

**C5. "Nothing found" is styled as an error.**
- *Where:* `search_wanted_item` returns 404, so a red toast.
- *Fix:* Return 200 and show a neutral toast: "Nothing yet — it'll be looked for again."

**C6. Asking for a book is one irreversible tap.**
- *Where:* Get book card → request and immediate search.
- *Fix:* The books pattern for a slip, an Undo toast: "Asked for Dune · Undo" (the DELETE already exists). Start the search a few seconds later so Undo really undoes.

**C7. Silent failures.**
- *Where:* "Search all now", job Run, Import Delete (`await apiFetch` with no catch); `refresh()` on Downloads swallows errors and leaves stale rows.
- *Fix:* Toast errors with the existing `run()` helper. After two failed refreshes, dim the lists with "Can't reach the library — retrying".

**C8. Get searches can race, and the sources run in series.**
- *Where:* `search()` has no generation guard (the books shelf has `loadGeneration`). `get_search` asks Open Library and then ComicVine, one after the other.
- *Fix:* Add the guard, and use two requests so each section fills as soon as its source answers.

**C9. Monitor changes reload the page and don't say what happened.**
- *Fix:* Update in place and toast "Getting all 14 missing issues" / "Getting new issues only".

**C10. Searching works through the backlog unevenly.**
- *Where:* `search_wanted(limit=50)` always takes the first 50 of each kind.
- *Fix:* Take the longest-unsearched first, so every wanted item gets its turn. Nothing visible changes.

---

## D. Missing states

**D1. Covers that don't load.**
- *Where:* `_covers.html` / `coverCard`: the `<img>` *replaces* the typographic `.cover-blank`.
- *Seen:* Get results are blank rectangles until Open Library answers. A failed ComicVine cover is a broken-image glyph with blue alt text.
- *Fix:* Always render `.cover-blank` under the image, and `onerror` removes the image (this helps books too).

**D2. Long names.**
- *Seen:*
  - The comics shelf caption truncates "LUMEN PRESS · #12 · 50…", cutting your progress.
  - Downloads rows push the date into the title.
  - Import hints are cut mid-word.
  - The comic reader drops the issue number on phones.
- *Fix:*
  - The in-progress caption leads with progress ("#12 · 50%"), as books' caption ends with it, and drops the publisher when space is short.
  - Entry titles wrap to two lines on phones.
  - The import hint gets its own line.
  - The reader title keeps "#12" (A1).

**D3. Get "In your library" is matched by title only.**
- *Seen:* Brian Herbert's *Dune* shows as owned if you have Frank Herbert's.
- *Fix:* Match title plus author surname. Owned results open the book, as on the shelf.

**D4. A series with no issues gives you nothing to do.**
- *Now:* it says "No issues yet".
- *Fix:* Use the shelf's `empty-state` with *Refresh details* (admins).

---

## E. Mobile (375 px, touch)

**E1. Tap targets under 44 px.**
- Shelf nav: Get 27×28, Comics 58×28, Downloads 106×28.
- Series: filters 21–63×28 (fixed by A4); header ⋯ 42×34; "ComicVine" link 71×17.
- Cover ⋯ buttons: 40×40. Downloads ⋯: 40×40.
- *Fix:* Pad the hit areas to 44 px without changing the look.

**E2. Meaning in tooltips.**
- *Where:* the comic reader's ⇄ / ↕ / Fit, "When you asked for it", "Which issues to download", the series description on Get results.
- *Fix:* A1 puts the reader options into words in the `Aa` sheet, A13 labels the dates, and B4 removes the monitor select. Drop the Get description tooltip; the series page shows the description.

**E3. Overlays.**
- *Where:* the release picker is a centred dialog. The books details panel becomes a bottom sheet on phones.
- *Fix:* Use the same `.metadata-overlay` mobile sheet behaviour (it already reuses the class; it just needs the panel's mobile rules and home-bar padding). `openMenu` near the bottom edge should respect `env(safe-area-inset-bottom)`.

**E4. Get on a phone buries comics.**
- *Now:* under *All*, 20 book covers come first (about 10 screens).
- *Fix:* Under *All*, show the first 6 of each section. The section's title switches the existing segment to Books or Comics to see the rest.

**E5. Settings "Largest download".**
- *Now:* "[100] MB a book [600]" with "MB a comic" wrapped away from its field.
- *Fix:* Two labelled fields (falls out of A7).

---

## F. Copy

| Where | Now | Suggested |
|---|---|---|
| Grab toasts | "Grabbed Starfall.013.2023.Digital.Zone-Empire.cbz" / "Sent … to SABnzbd" | "Downloading Starfall #13" |
| Series search | "Grabbed 3" / "Nothing new on the indexers" | "Downloading 3 issues" / "Nothing new yet" |
| Release picker | "Asking the indexers…" · "3 of 12 fit." · "The indexers have nothing for it." · **Grab** | "Searching…" · "3 of 12 match" · "Nothing found yet" · **Download** |
| Item menus | "Search now" · "Pick a release…" | "Find now" · "Choose a release…" |
| Wanted button and hint | "Search all now" · "Searched for every few hours." | "Find now" · "Looked for every 6 hours." (from the setting) |
| Get toast | "Getting Dune; it shows up in Downloads" | "Asked for Dune · Undo" |
| Get intro | "…Tap a cover to get it." | "Choose a cover to ask for it." |
| Import row | title `starfal_15_preview.cbz`; "Matches Starfall (2023) #15; it's filed at the next import" | "Starfall #15?", filename muted under it; "Will be filed as Starfall #15" |
| Import toast | "Imported 2; 1 to match by hand; 1 unreadable" | "Added 2. 1 needs a series. 1 couldn't be opened." |
| Active blackhole row | "Waiting for the file" | "Waiting for your download client" |
| Failures | "qBittorrent: stalledDL" · "SABnzbd didn't answer (ConnectError)." · "Its file never showed up in the import folder." | "Its files went missing from qBittorrent" · "SABnzbd isn't answering" · "The file never arrived" |
| Jobs | "The worker hasn't checked in for a while; it starts when the app gets its first visit after a restart." | (section removed, B1) "Downloads are paused." |
| Comic reader end | "The end." · "Back to the last page" | `chapter-end`: "NEXT  #13 →" (A1) |
| Comic reader, no pages | "This file has no pages." | "This file is empty or damaged." |
| Server: monitor | "Pick all, future or none." | "Choose New issues, All missing or None." |
| Server: settings test | "Test what?" | "Nothing to test here." |
| Server: retry | "What it was for is gone." | "That isn't wanted any more." |
| Server: picker | "That list is out of date; search again." | "These results have expired. Search again." |
| `apiFetch` fallback | "Something went wrong (502)." | "Couldn't reach the library. Try again." |
| Downloads ⋯ aria-label | "More" | "More for Starfall #13" |

---

## Top 10

| # | Fix | Why | Size |
|---|---|---|---|
| 1 | **Comic reader built from the book reader** (A1): `top-controls`, `Aa` sheet (Pages / Fit / Direction / Theme), reader themes and night switch, progress line, `chapter-end`, `?` sheet, Esc never leaves | The biggest "different app" moment, and it fixes Fit being missing on phones | Large |
| 2 | **No pills, no ✓; state in the caption** (A2, A3) | Makes every comic wall read like the books wall, and clears the touch clutter | Medium |
| 3 | **Offline parity for comics** (A11): last 12 issues, banner and dimming, queued progress, shell precache | "Reader on the go" works for books but not comics | Large |
| 4 | **One menu, in-app confirms, one filter** (A4, A5): no `confirm()`, `discard-bar`-style confirms, `openMenu` everywhere, the shelf's filter on series | Removes the native dialogs and the odd-one-out controls | Medium |
| 5 | **Series header like the details panel; monitor only in ⋯; reading order for all** (A6, B4, B5) | The series page becomes a reading page, as books' details are | Small |
| 6 | **Settings and Import in the details panel's form style, no cards** (A7, E5) | The last screen that looks like a different product | Medium |
| 7 | **Downloads tells the truth** (C2, C3, C4, C5, B3): stalled named, failures on top in plain words, client trouble said once, honest badge | Trust | Medium |
| 8 | **Remove jobs and Coming up from Downloads** (B1, B2) plus the copy pass (A9, F) | Downloads goes back to "is my thing coming?" | Small |
| 9 | **Get behaves like the shelf** (A2, A12, C6, C8, D1, D3, E4): skeletons, typographic fallback covers, caption states, Undo on asking, parallel sources, comics visible on phones | The main way in stops feeling like a form | Medium |
| 10 | **Follow without waiting** (C1), `/` on Comics and Get (A10), 44 px targets (E1) | Small things you hit every session | Small |

---

## Cut from the previous version (extraneous)

These add screens, sheets or features the books app doesn't have:
- A trash and Undo for comic files (books delete with Undo, but there's no trash screen).
- A "follow" sheet on Get.
- A "Recently asked for" row on Get.
- "Out this week" on the comics shelf.
- A Maintenance block in Settings.
- A danger dot on the Downloads badge.
- An ETA and speed on downloads.
- "Last searched 3 h ago" per wanted item.
- "Keep offline" per issue (comics will keep recent issues automatically, as books do).
- "Mark all read" and "Continue" in a series cover menu.
- A pinned Continue button.
- 3-up issue walls on phones.
- A "New" mark on the books shelf.
- "Follow and stay".
- Shortcut keys books don't have (`C`, `S`, `G`-chords).
- A "Fetching issues" poll with an error timeout (now one line, C1).
