# Table of Contents Resolution

How `library/utils.py:get_epub_structure()` decides what appears in the
reader's sidebar for a given EPUB.

## Why this is hard

EPUBs are messier than the spec suggests. Real-world books we have to handle:

- **EPUB3 with a clean nav doc** — the easy case.
- **EPUB2 with a working NCX** — also easy.
- **EPUBs with a broken nav/NCX** — e.g. an NCX with one entry pointing at a
  filename that isn't even in the spine. Common in older Calibre-generated
  files.
- **EPUBs whose only real TOC is a Contents page in the spine** — the
  publisher styled "CONTENTS" with a `<span>` and listed chapters as `<a>`
  tags. The reader sees a TOC; the machine-readable nav is broken or absent.
- **EPUBs with no semantic markup at all** — chapter titles rendered as
  decorative spans/divs, no `<h1>`/`<h2>`, no nav, no Contents page.

Our resolution chain handles each case in order, falling through to the next
when the current one yields nothing usable.

## The resolution chain

```
1. EPUB3 nav doc   (manifest item with properties="nav")
        ↓ (empty after spine resolution?)
2. EPUB2 NCX       (toc.ncx, located via spine[toc] or media-type)
        ↓ (empty after spine resolution?)
3. Contents page   (in-content TOC found by scanning front matter)
        ↓ (no page passes both validation factors?)
4. Synthetic       (flat "Section 1 … N" list with synthetic=True)
```

Each layer's output is passed through `_resolve_toc_to_spine()`, which maps
hrefs to spine indices and drops entries that don't match any spine item.
We move to the next layer **only when the current one resolves to zero
entries** — even one valid entry from the publisher is trusted over
heuristics.

### 1. EPUB3 nav doc

Looks for a manifest `<item>` with `properties="nav"`. Parses its XHTML for a
`<nav epub:type="toc"><ol>…</ol></nav>` (falls back to any `<nav>`).
Hierarchy is preserved: nested `<ol>` inside `<li>` becomes `children` in
the resulting tree.

### 2. EPUB2 NCX

Looks for `<spine toc="…">` pointing at a manifest item, or any item with
media-type `application/x-dtbncx+xml`. Walks `<navMap>/<navPoint>` recursively.
Same hierarchy preservation.

### 3. In-content Contents page (the interesting one)

Scans the **first 15 spine items** (Contents pages are always front matter)
and applies a two-factor test to each:

**Factor 1 — does this document present itself as a Contents page?**

- Has an `<h1>`/`<h2>`/`<h3>` whose entire text is "Contents", "Table of
  Contents", or "TOC"; OR
- Has `<meta name="chapter-title" content="Contents">` (Calibre's hint); OR
- Has `<title>` in `<head>` saying Contents; OR
- Has any short standalone text node literally saying "CONTENTS"
  (catches `<p><span class="sgc2">CONTENTS</span></p>` patterns)

**Factor 2 — do its links actually behave like a TOC?**

- ≥ 3 `<a href>` links resolve to spine items
- ≥ 80% of all `<a href>` on the page resolve to spine items

The second factor is the safety net: a regular chapter that uses the word
"Contents" in prose will still have lots of unresolved links (footnotes,
external URLs) and gets rejected.

**Why this matters**: real-world publisher EPUBs frequently have a broken
NCX *and* a perfect Contents page in the spine. The Contents page captures
exactly what the publisher intended for the reader to navigate to —
including section anchors (`#fragment`) that scroll to the right offset
within a file. Heuristic-based chapter detection cannot match this.

### 4. Synthetic fallback

Generates a flat list `Section 1, Section 2, …, Section N` for every spine
item. Each entry carries `synthetic: true`. The reader frontend uses that
flag to **progressively replace placeholder titles** with whatever
`get_chapter_title()` extracts from each chapter's HTML as it streams in.

## `get_chapter_title()` heuristics

Used in two places:
1. By the synthetic fallback's frontend backfill (one chapter at a time).
2. By any future spine-walking detector if we ever add one.

Tried in order; first non-empty result wins:

1. **`epub:type="chapter|title|subtitle"`** — strongest semantic signal.
2. **Heading tags by specificity**: `h1` first, then `h2`, then `h3`.
   Skips `h4`-`h6` (almost always sub-section labels).
3. **Common chapter-title CSS class / id** — regex covers `chapter-title`,
   `chapterTitle`, `chapter_title`, `chapter-heading`, `section-title`,
   `heading`.
4. **`<title>` in `<head>`** — often generic but better than nothing.
5. **Filename-derived** — strip `chapter|ch|section|part` prefix, titlecase
   the result.
6. **First short paragraph** under 60 characters — chapter epigraphs / openers.

**Always skips elements inside `<nav>`** so a contents page doesn't return
"Contents" as its title.

Whitespace is normalized via `_clean_title()` (collapses runs of whitespace
and newlines).

## Spine items that aren't in the TOC

Whatever resolution layer wins, the result is usually a **subset** of the
spine. Front matter (titlepage, copyright, dedication) and the Contents page
itself typically aren't listed.

These items remain readable: the reader's next/prev buttons walk the entire
spine, not just TOC entries. They just don't appear in the sidebar.

## What we explicitly don't do

**Spine-walking with content-based chapter detection.** The plan was: walk
every spine item, filter front matter (titlepage/copyright by filename,
files with body text under ~150 chars), and use `get_chapter_title()` to
title each survivor.

We don't do this because:

- For books with a publisher-provided TOC (nav, NCX, or Contents page) it
  duplicates work and risks worse titles.
- For books with no TOC at all, `get_chapter_title()` often returns `None`
  because publishers love decorative `<span>`s instead of `<h1>`s. So the
  output would be only marginally better than the synthetic fallback.
- The synthetic fallback already does title backfill via the streaming
  frontend, lazily. Spine-walking would just shift that to metadata-time.

If we hit books where the synthetic sidebar is full of mystery placeholders,
this would be the next ~30 LOC to add as an extra layer between Contents
page and synthetic.

## File map

| File | Purpose |
|---|---|
| `library/utils.py:get_epub_structure()` | Orchestrator — runs the chain. |
| `library/utils.py:_read_epub_toc()` | Layers 1 & 2 (nav doc, NCX). |
| `library/utils.py:_find_contents_page()` | Layer 3. |
| `library/utils.py:_has_contents_marker()` | Layer 3 — Factor 1. |
| `library/utils.py:_resolve_toc_to_spine()` | Maps href → spine index, drops misses. |
| `library/utils.py:get_chapter_title()` | Used by frontend backfill on layer 4. |
| `library/static/js/reader.js` | Renders the sidebar; backfills synthetic titles. |
| `tests/test_utils.py` | Coverage for every layer + heuristic. |
