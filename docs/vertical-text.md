# Vertical text (直排): plan

Chinese books read top to bottom, in lines from right to left, with pages turning to the left, like a printed Traditional Chinese book. A per-book reader setting, built on the reader's existing Pages mode.

## When it's offered

- **Only for Chinese (and Japanese) books**: the book's or the chapter's language is `zh*`, `yue*` or `ja*` (the same language data read aloud uses).
- **Only in Pages mode.** Vertical text flows sideways, so Scroll mode would mean scrolling through a chapter sideways: clumsy on a desktop, worse on a phone. Choosing Vertical switches to Pages. Scroll mode is greyed out while vertical is on, with a one-line reason.
- **Setting:** `Aa → Text direction: Horizontal / Vertical`, remembered per book.
- **Default:** vertical when the EPUB asks for it: `page-progression-direction="rtl"` in its spine, or `writing-mode: vertical-rl` in its CSS (Haodoo's 直式 editions). Horizontal otherwise. The book's own `writing-mode` is otherwise dropped by the style filter (`utils.book_style_subset`), and stays dropped; the reader decides.

## How the page works

Measured in Chrome (October 2026): with `writing-mode: vertical-rl`, CSS columns stack top to bottom, so columns, which the horizontal Pages mode uses, page *downwards*. Instead:

- The chapter is one `vertical-rl` block of fixed height (the screen, less the margins). It overflows to the **left**, and `scrollLeft` runs from 0 to negative, as standardised.
- **A page is one screen of lines**, and the next page is further left. Single pages only at first. A two-page spread would need a gutter in the middle of a single flowing block, which this layout can't make; see the open questions.
- **Pages break between lines.** A fixed step cuts lines in half wherever paragraph spacing knocks them off the grid (seen in the test). So the page starts are worked out from the lines themselves: walk the text's line boxes (`Range.getClientRects`) and start each page at the first line that didn't fully fit on the one before. The same list then gives the page count, "page n of m", and which page holds any element or sentence.
- **On wide screens** the page is capped (around 40 lines) and centred, so it doesn't become a wall of columns.
- **Your place** is saved as before, a fraction through the chapter, now measured from the right: `-scrollLeft / (scrollWidth - clientWidth)`. Switching direction keeps you on the same paragraph, as changing the text size already does.

## Turning pages

Everything mirrors, as in a printed vertical book:

| | Horizontal | Vertical |
|---|---|---|
| Next page | → key, tap the right side, swipe left | ← key, tap the **left** side, swipe **right** |
| Previous page | ← key, tap the left side, swipe right | → key, tap the right side, swipe left |
| Next / previous section | Shift + → / ← | Shift + ← / → |
| Progress bar | fills left to right | fills right to left |

## Typography

- **Font:** a Traditional Chinese serif (`Songti TC` on Apple devices, `Noto Serif TC` elsewhere), with line spacing around 1.8–2. The Aa line-spacing choices still apply.
- **Punctuation:** `text-orientation: mixed`, plus the font's vertical forms, puts 。，、 in the right place and turns 「」『』 and ⋯⋯ correctly; checked in Chrome. Traditional (TC) fonts centre punctuation, the Taiwan convention, which suits these books.
- **Numbers and short Latin runs:** one or two digits stand upright, combined into one cell ("第1段" → upright 1; "12月" → upright 12). Longer numbers and English words run sideways, as in print. This is done by wrapping digit runs of 1–2 in a `text-combine-upright: all` span when the chapter is rendered, since `digits 2` isn't supported widely enough.
- **Paragraphs:** no space between them; Chinese books open each one with a two-character indent (　　), which most, including Haodoo's, already have. Headings keep their space.
- **Images** stay upright, sized to the page height. A full-page image gets its own page.

## Everything else that knows about pages

- **Running head and foot:** the chapter title along the right edge, and the page and time left along the bottom, in the reader's mono style.
- **Footnote popovers, the Ask/Explain selection menu, search results, the "Back" pill, the chapter-end button and the "Finished?" offer:** each placed relative to its text, so each gets checked in vertical mode; most should just work.
- **Read aloud:** sentence and word highlighting work unchanged. The page-following needs the line-based page list to find a sentence's page.
- **Text size and line-spacing changes** relayout and keep your paragraph, as now.

## Steps

1. **Layout and paging:** the vertical block, the line-based page list, page turns in every direction, saving and restoring your place. Behind the setting, Chinese books only.
2. **Typography:** numbers upright, paragraph spacing, font and punctuation checks, images.
3. **The rest of the reader:** running head and foot, notes, selection, search, read-aloud following, chapter ends.
4. **Defaults:** vertical when the EPUB asks for it, the per-book setting, and Scroll mode greyed out.

Testing: automated in Chrome and WebKit, Safari's engine (`playwright install webkit`), on 吶喊 and a vertical Haodoo edition; then on your iPhone. iOS Safari is where vertical layout is most likely to differ.

Effort: step 1 is the bulk; the reader's paging assumes left-to-right columns in about a dozen places. Steps 2–4 are smaller.

## Open questions

- **Two-page spreads on a laptop?** Not possible with one flowing block. Rendering the chapter twice, side by side and offset by a page, would work, at the cost of selection and read aloud seeing two copies. Single pages first; see whether a laptop wants more.
- **Vertical by default for every Chinese book,** or only when the EPUB asks for it? Starting with "when it asks", plus the setting.
