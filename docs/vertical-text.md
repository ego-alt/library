# Vertical text (直排)

Chinese and Japanese books can read top to bottom, in lines from right to left, with pages turning to the left, like a printed Traditional Chinese book. Built October 2026; this note says how it works and what's left.

## When it's offered

- **Only for Chinese and Japanese books**: the book's or the chapter's language is `zh*`, `yue*`, `cmn*` or `ja*`, or, for a book with no language at all, its text is mostly Chinese or Japanese characters (`verticalAvailable` in `reader.js`).
- **Setting:** `Aa → Text direction: Horizontal / Vertical`, remembered per book on each device (`textDirection:<file>` in local storage).
- **Default:** vertical when the book asks for it: `page-progression-direction="rtl"` on its spine, or `writing-mode: vertical-rl` (or the old `tb-rl`, with or without a prefix) in its CSS. `utils.get_epub_structure` sends this as `vertical` with the book's metadata. A right-to-left Arabic or Hebrew book isn't affected, since only Chinese and Japanese books are offered vertical text. The book's own `writing-mode` is still dropped by the style filter (`utils.book_style_subset`); the reader decides.
- **Always in pages.** Vertical text would scroll sideways, so while it's on the Scroll button is greyed out, with "Vertical text reads in pages." Your Scroll/Pages choice for other books isn't changed.

## How the page works

With `writing-mode: vertical-rl`, CSS columns stack downwards, so the horizontal Pages mode's columns can't be used. Instead (`layoutVerticalChapter`):

- The chapter is one `vertical-rl` block a page high. It overflows to the **left**, and `scrollLeft` runs from 0 to negative.
- **A page is a screen of whole lines.** `verticalLines` collects every line (and picture) as a span measured from the chapter's right edge; a new page starts at the first line that wouldn't fit on the one before, midway between the two lines. The part of the next page's first line that would show at the left edge is clipped (`clip-path`). A fixed step would cut lines in half wherever paragraph spacing knocks them off a grid.
- **Wide screens:** a page is at most 40 lines, centred.
- An empty filler a page wide ends the chapter, so the last page can be brought to the right edge.

## Your place

Where a page starts is kept as **a character offset into the chapter's text** (`firstVisibleTextOffset`), not a paragraph: in books whose chapters are one long block of lines (as Haodoo's are), a paragraph is the whole chapter. Text size, line spacing, resizing and switching direction all land back on the page holding that character. This also fixed horizontal Pages mode for those books, which used to jump back to the chapter's first page on a text-size change.

The saved bookmark is still a fraction of the chapter's pages, as in horizontal Pages mode.

## Turning pages

| | Horizontal | Vertical |
|---|---|---|
| Next page | → key, tap the right side, swipe left | ← key, tap the **left** side, swipe **right** |
| Previous page | ← key, tap the left side, swipe right | → key, tap the right side, swipe left |
| Next / previous section | Shift + → / ← | Shift + ← / → |
| Progress hairline | fills left to right | fills right to left |

Space and Page Down still go onwards in both.

## Typography

- **Font:** a Traditional Chinese serif (`Songti TC` on Apple devices, `Noto Serif TC` elsewhere), with a little more line spacing than horizontal text. Chinese and Japanese chapters use the same serif in horizontal text too (`.cjk`, set by `isCjkChapter`); an English passage inside keeps Inter. The `Aa` line-spacing choices still apply.
- **Punctuation:** `text-orientation: mixed` with the font's vertical forms puts 。，、 in place and turns 「」 and ⋯⋯.
- **Numbers:** a run of one or two digits stands upright in one cell ("第1段", "12月"), wrapped in a `text-combine-upright` span when the chapter renders (`uprightDigits`). Longer numbers ("2024年"), decimals and Latin words ("A4") run sideways, as in print.
- **Paragraphs:** no space between them; they open with their own two-character indent. The book's margins, made for horizontal text, are dropped. Headings get space before and after.
- **Pictures** stay upright, sized to fit the page.

## Everything else that knows about pages

- **Read aloud** follows the sentence onto its page, using the same page list (`pageOfRect`, `visiblePageRect`).
- **Contents, footnote links, "Back", time left and the "Finished?" offer** work unchanged.
- **Running head and foot** stay in the top and bottom margins; the chapter title is set to the right, where the text begins.

## Testing

Checked in Chrome at desktop and phone sizes, on 吶喊 (a horizontal edition, switched under `Aa`) and on a copy marked right-to-left (vertical by default): paging by whole lines, turning by keys and taps, keeping your place through text size, resizing and direction switches, numbers, night mode, and English books unchanged. Server tests: `tests/test_vertical_text.py`.

Not yet checked on an iPhone. iOS Safari is where vertical layout is most likely to differ (negative `scrollLeft`, line measuring, `text-combine-upright`).

## Not done

- **Two-page spreads on a laptop.** One flowing block can't make a gutter in the middle. Rendering the chapter twice, side by side and offset by a page, would work, at the cost of selection and read aloud seeing two copies. Single pages first; see whether a laptop wants more.
- **The chapter title along the right edge** instead of the top margin, as some vertical books print it.
