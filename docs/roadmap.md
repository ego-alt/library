# Library roadmap

What's left to do. The audits it came from (the UX audit of October 2026 and the comics audit of 25 October) are in git history; everything else from them is done, as far as the code shows.

- **The comic reader as the book reader with pages.** The comics audit asked for the book reader's top bar and `Aa` sheet, with Pages, Fit, Direction and Theme in it. The comic reader has fit, direction and theme settings of its own, but not that shared bar and sheet.
- **Cascade deletes on `book_tags`.** Databases from before May 2026 kept `book_tags` foreign keys without `ON DELETE CASCADE` (autogenerate doesn't detect it, so it needs a hand-written batch migration). Harmless today: purging a book clears its tag rows itself.
