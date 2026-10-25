let currentBook = null;
let currentChapter = null;
const filename = window.location.pathname.split('/').pop();

let allChapters = [];
let currentChapterNum = 0;
let currentPagePosition = 0;
let currentFontSize = parseInt(localStorage.getItem('readerFontSize')) || 17;
let lastSaveTimeout = null;

let selectedRange = null;
let hrefChapterMapping = {};

// Reading mode: 'scroll' (default, vertical) or 'paginate' (CSS column-based
// horizontal pagination). Bookmark.position is a 0..1 fraction in both modes;
// scroll mode treats it as scrollY/scrollHeight, paginate mode as
// currentPageIndex / (totalPages - 1).
let readingMode = localStorage.getItem('readingMode') === 'paginate' ? 'paginate' : 'scroll';
let currentPageIndex = 0;   // index of the *spread* currently visible
let totalPages = 1;          // total number of spreads
let spreadCount = 1;         // 1 (one page) or 2 (two-page spread)
const PAGE_GAP = 72;           // the centre gap of a two-page spread
// Page width caps, in ems of the default 17px text (about 62 characters a
// line at that size). Wider screens get wider margins, not longer lines.
const PAGE_MAX_EM = {narrow: 25, normal: 29, wide: 33};
const SPREAD_WIDTH_THRESHOLD = 1000; // px — show 2-up when viewport is at least this wide

// Vertical text (直排), for Chinese and Japanese books: lines run top to
// bottom and follow each other leftwards, and the pages turn to the left, as
// in a printed vertical book. Always in pages. Set per book under Aa; the
// default is what the book asks for (metadata.vertical). See docs/vertical-text.md.
const VERTICAL_KEY = `textDirection:${filename}`;
const CJK_LANG = /^(zh|yue|cmn|ja)\b/i;
const HAN_TEXT = /[㐀-鿿豈-﫿぀-ヿ]/g;
const VERTICAL_MAX_LINES = 40;   // wide screens: a page of at most this many lines, centred
let pageStarts = [0];            // vertical: where each page begins, px from the chapter's start (its right edge)

// A Chinese or Japanese book: by its language tags, or (untagged) its text.
function verticalAvailable() {
    if (!currentBook) return false;
    const chapter = allChapters[currentChapterNum];
    if (CJK_LANG.test(currentBook.language || '') || CJK_LANG.test((chapter && chapter.lang) || '')) return true;
    if (currentBook.language) return false;
    const sample = (document.getElementById('chapter-content')?.textContent || '').slice(0, 2000);
    return (sample.match(HAN_TEXT) || []).length > sample.replace(/\s/g, '').length * 0.5;
}

// This chapter is Chinese or Japanese: by its own language tag, else the
// book's, else (untagged) its text.
function isCjkChapter() {
    const chapter = allChapters[currentChapterNum];
    const tag = (chapter && chapter.lang) || (currentBook && currentBook.language) || '';
    if (tag) return CJK_LANG.test(tag);
    const sample = (document.getElementById('chapter-content')?.textContent || '').slice(0, 2000);
    return (sample.match(HAN_TEXT) || []).length > sample.replace(/\s/g, '').length * 0.5;
}

function isVertical() {
    if (!verticalAvailable()) return false;
    const chosen = readerSetting(VERTICAL_KEY, '');
    return chosen ? chosen === 'vertical' : Boolean(currentBook.vertical);
}

function isPaginated() { return readingMode === 'paginate' || isVertical(); }

function applyReadingModeClass() {
    document.documentElement.classList.toggle('paginated', isPaginated());
    document.documentElement.classList.toggle('vertical', isVertical());
}

function updateReadingModeButton() {
    if (typeof syncSettingsPanel === 'function') syncSettingsPanel();
}

function computeSpreadCount() {
    return window.innerWidth >= SPREAD_WIDTH_THRESHOLD ? 2 : 1;
}

// Scroll distance to advance one user-visible "page" (= a 1- or 2-column spread).
function spreadStep() {
    const css = getComputedStyle(document.documentElement);
    const colW = parseFloat(css.getPropertyValue('--col-w')) || 0;
    const colGap = parseFloat(css.getPropertyValue('--col-gap')) || 0;
    return spreadCount * (colW + colGap);
}

// Recompute layout variables and totalPages for the current chapter. Forces
// synchronous reflow by reading clientWidth and scrollWidth so the result is
// usable immediately by the caller.
function layoutPaginatedChapter() {
    if (!isPaginated()) return;
    const content = document.getElementById('chapter-content');
    const reader = document.getElementById('reader-content');
    if (!content || !reader) return;
    content.querySelector(':scope > .page-filler')?.remove();
    if (isVertical()) return layoutVerticalChapter(content, reader);
    content.style.clipPath = '';

    spreadCount = computeSpreadCount();
    // Measured at the default text size, so changing the size reflows the
    // text but leaves the page where it is; only Width moves the margins.
    const pageMax = (PAGE_MAX_EM[readerSetting('readerWidth', 'normal')] || 29) * 17;
    const container = reader.closest('.reader-container');
    const cs = container ? getComputedStyle(container) : null;
    const padX = cs ? parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) : 60;
    const maxW = Math.round(spreadCount * pageMax + (spreadCount - 1) * PAGE_GAP + padX);
    document.documentElement.style.setProperty('--reader-max-w', maxW + 'px');

    // Reading clientWidth flushes layout with the new max-width applied.
    const w = reader.clientWidth;
    const h = reader.clientHeight;
    if (w <= 0 || h <= 0) return;

    const colW = (w - (spreadCount - 1) * PAGE_GAP) / spreadCount;
    document.documentElement.style.setProperty('--col-w', colW + 'px');
    document.documentElement.style.setProperty('--col-gap', PAGE_GAP + 'px');
    document.documentElement.style.setProperty('--page-h', h + 'px');

    // Flush so scrollWidth reflects the new column layout.
    void content.offsetHeight;

    const step = colW + PAGE_GAP;
    // A chapter that ends on a left-hand page can't scroll a full spread
    // further, so the last spread would slide back and repeat a column. Give
    // it a blank right-hand page instead, as a printed book would.
    let totalCols = Math.max(1, Math.round(content.scrollWidth / step));
    if (spreadCount > 1 && totalCols % spreadCount) {
        const filler = document.createElement('div');
        filler.className = 'page-filler';
        filler.setAttribute('aria-hidden', 'true');
        content.appendChild(filler);
        void content.offsetHeight;
        totalCols = Math.max(1, Math.round(content.scrollWidth / step));
    }
    totalPages = Math.max(1, Math.ceil(totalCols / spreadCount));
    currentPageIndex = Math.max(0, Math.min(currentPageIndex, totalPages - 1));
    applyPageTransform(false);
}

// Vertical pages: the chapter is one vertical-rl block a page high, flowing
// to the left (scrollLeft runs from 0 to negative). CSS columns can't page it
// sideways (in vertical-rl they stack downwards), and a fixed step would cut
// lines in half wherever paragraph spacing knocks them off a grid. So a page
// is a screen of whole lines: each starts at the first line that didn't fit
// on the one before, and anything past the page's last line is clipped.
function layoutVerticalChapter(content, reader) {
    spreadCount = 1;
    const pitch = parseFloat(getComputedStyle(content).lineHeight) || currentFontSize * 1.9;
    const container = reader.closest('.reader-container');
    const cs = container ? getComputedStyle(container) : null;
    const padX = cs ? parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) : 60;
    document.documentElement.style.setProperty('--reader-max-w', Math.round(VERTICAL_MAX_LINES * pitch + padX) + 'px');

    const w = reader.clientWidth;
    const h = reader.clientHeight;
    if (w <= 0 || h <= 0) return;
    document.documentElement.style.setProperty('--col-w', w + 'px');
    document.documentElement.style.setProperty('--page-h', h + 'px');
    void content.offsetHeight;

    pageStarts = [0];
    let start = 0, prevEnd = 0;
    for (const [a, b] of verticalLines(content)) {
        // A new page starts midway between the last line that fit and this one.
        if (b - start > w + 1 && a > start + 1) {
            start = Math.round((prevEnd + a) / 2);
            pageStarts.push(start);
        }
        prevEnd = b;
    }
    // Room to bring the last page to the right edge.
    const filler = document.createElement('div');
    filler.className = 'page-filler';
    filler.setAttribute('aria-hidden', 'true');
    content.appendChild(filler);

    totalPages = pageStarts.length;
    currentPageIndex = Math.max(0, Math.min(currentPageIndex, totalPages - 1));
    applyPageTransform(false);
}

// The chapter's lines (and pictures) in order, as [start, end] in px from its
// start (right) edge. Glyph boxes of one line overlap, so they're merged.
function verticalLines(content) {
    const origin = content.getBoundingClientRect().right - content.scrollLeft;
    const spans = [];
    const add = (r) => { if (r.width > 0 && r.height > 0) spans.push([origin - r.right, origin - r.left]); };
    const range = document.createRange();
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.data.trim()) continue;
        range.selectNodeContents(n);
        for (const r of range.getClientRects()) add(r);
    }
    content.querySelectorAll('img, svg, hr, table').forEach((el) => add(el.getBoundingClientRect()));
    spans.sort((x, y) => x[0] - y[0]);
    const lines = [];
    for (const [a, b] of spans) {
        const last = lines[lines.length - 1];
        if (last && a < last[1] - 1) last[1] = Math.max(last[1], b);
        else lines.push([a, b]);
    }
    return lines;
}

// The page a box on screen is on.
function pageOfRect(r) {
    const content = document.getElementById('chapter-content');
    const box = content.getBoundingClientRect();
    if (isVertical()) {
        const at = box.right - content.scrollLeft - r.right;
        let page = 0;
        while (page + 1 < pageStarts.length && pageStarts[page + 1] <= at + 1) page++;
        return page;
    }
    const x = r.left - box.left + content.scrollLeft;
    const step = spreadStep();
    return step > 0 ? Math.max(0, Math.floor(x / step)) : 0;
}

// The part of the chapter's box that shows the current page (a vertical
// page can be narrower than the screen: it ends with its last whole line).
function visiblePageRect() {
    const box = document.getElementById('chapter-content').getBoundingClientRect();
    if (!isVertical()) return box;
    const start = pageStarts[currentPageIndex] || 0;
    const next = pageStarts[currentPageIndex + 1];
    const width = next === undefined ? box.width : Math.min(box.width, next - start);
    return {left: box.right - width, right: box.right, top: box.top, bottom: box.bottom, width, height: box.height};
}

// Recompute the paginated layout and land back on the same content: the
// text that started the page (a resize, a font change, an image arriving),
// or, when restoring a saved place, a fraction of the chapter.
function relayoutPreservingPosition(fraction) {
    // The place remembered when the page last settled: by now a resize or
    // font change has already reflowed the pages, so measuring now would
    // find whatever slid onto the page instead.
    const remembered = _pageAnchor && _pageAnchor.chapter === currentChapterNum && _pageAnchor.offset >= 0
        ? _pageAnchor : null;
    const anchor = fraction === undefined ? remembered : null;
    const fallback = fraction === undefined ? currentPositionFraction() : fraction;
    layoutPaginatedChapter();
    const rect = anchor && rectAtTextOffset(anchor.offset);
    currentPageIndex = rect
        ? Math.min(pageOfRect(rect), Math.max(0, totalPages - 1))
        : Math.round(fallback * Math.max(0, totalPages - 1));
    applyPageTransform(false);
    // Keep the same place across repeated relayouts (resizing through
    // several widths), rather than whatever now starts the page.
    if (anchor) _pageAnchor = anchor;
    updateProgressBar();
    updateChapterNumberLabel();
}

// Where the page (or, scrolling, the screen) starts, as a character offset
// into the chapter's text. Unlike a paragraph, it's exact in books whose
// chapters are one long block of lines, and it survives re-rendering the
// chapter (numbers set upright or not).
function firstVisibleTextOffset() {
    const content = document.getElementById('chapter-content');
    if (!content) return -1;
    const box = isPaginated() ? visiblePageRect() : null;
    const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
    // Not on an earlier page (or above the screen): earlier pages lie to the
    // left, a vertical book's to the right.
    const notBefore = (r) => (!box ? r.bottom > topBar + 4
        : isVertical() ? r.left < box.right - 1 : r.right > box.left + 1);
    const range = document.createRange();
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    let offset = 0;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        range.selectNodeContents(n);
        const rects = range.getClientRects();
        if (n.data.trim() && rects.length && notBefore(rects[rects.length - 1])) {
            // The first character of this text that's on the page.
            let lo = 0, hi = n.data.length - 1;
            while (lo < hi) {
                const mid = (lo + hi) >> 1;
                range.setStart(n, mid);
                range.setEnd(n, mid + 1);
                const r = range.getBoundingClientRect();
                if (r.width || r.height ? notBefore(r) : false) hi = mid; else lo = mid + 1;
            }
            return offset + lo;
        }
        offset += n.data.length;
    }
    return -1;
}

// The box of the character at a text offset (see firstVisibleTextOffset).
function rectAtTextOffset(offset) {
    const content = document.getElementById('chapter-content');
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (offset < n.data.length) {
            range.setStart(n, offset);
            range.setEnd(n, Math.min(offset + 1, n.data.length));
            const r = range.getClientRects()[0];
            return r || null;
        }
        offset -= n.data.length;
    }
    return null;
}

// Where the page started when it last settled (see relayoutPreservingPosition).
let _pageAnchor = null;
function rememberPageAnchor() { _pageAnchor = {chapter: currentChapterNum, offset: firstVisibleTextOffset()}; }

// The first paragraph (innermost text block) showing on the current page.
function firstVisibleBlock() {
    if (!isPaginated()) return null;
    const content = document.getElementById('chapter-content');
    if (!content) return null;
    const box = visiblePageRect();
    const blocks = content.querySelectorAll(':is(p, div):not(:has(p, div))');
    for (const b of blocks) {
        if (!b.textContent.trim()) continue;
        const r = b.getBoundingClientRect();
        if (!(r.right > box.left + 1 && r.left < box.right - 1 && r.bottom > box.top)) continue;
        // Its box overlaps the page; is any of its text actually on it?
        const range = document.createRange();
        range.selectNodeContents(b);
        for (const line of range.getClientRects()) {
            if (line.width > 1 && line.left >= box.left - 1 && line.right <= box.right + 1) return b;
        }
    }
    return null;
}

// Page turns are instant: a slide makes the text move on every page.
const PAGE_FLIP_MS = 0;
let _pageFlipRaf = null;

// Custom rAF animation: the browser's smooth scroll is ~300ms with no knob,
// and that feels slow for a page turn. 140ms ease-out lands snappy without
// the harshness of instant scroll.
function applyPageTransform(animate = true) {
    const content = document.getElementById('chapter-content');
    if (!content) return;
    if (isVertical()) {
        const start = pageStarts[currentPageIndex] || 0;
        const next = pageStarts[currentPageIndex + 1];
        content.scrollLeft = -start;
        // Hide the next page's first line where it peeks in at the left edge.
        const hidden = next === undefined ? 0 : Math.max(0, content.clientWidth - (next - start));
        content.style.clipPath = hidden ? `inset(0 0 0 ${hidden}px)` : '';
        rememberPageAnchor();
        return;
    }
    const targetLeft = currentPageIndex * spreadStep();

    if (_pageFlipRaf) {
        cancelAnimationFrame(_pageFlipRaf);
        _pageFlipRaf = null;
    }
    if (!animate || PAGE_FLIP_MS <= 0) {
        content.scrollLeft = targetLeft;
        rememberPageAnchor();
        return;
    }

    const startLeft = content.scrollLeft;
    const delta = targetLeft - startLeft;
    if (Math.abs(delta) < 1) {
        content.scrollLeft = targetLeft;
        rememberPageAnchor();
        return;
    }
    const startTime = performance.now();
    function step(now) {
        const t = Math.min(1, (now - startTime) / PAGE_FLIP_MS);
        // Ease-out cubic: fast start, gentle landing.
        const eased = 1 - Math.pow(1 - t, 3);
        content.scrollLeft = startLeft + delta * eased;
        if (t < 1) {
            _pageFlipRaf = requestAnimationFrame(step);
        } else {
            _pageFlipRaf = null;
            rememberPageAnchor();
        }
    }
    _pageFlipRaf = requestAnimationFrame(step);
}

// Measured by bounding rect; offsetLeft would be wrong if any intermediate
// ancestor is positioned.
function pageOfElement(el) {
    return el ? pageOfRect(el.getBoundingClientRect()) : 0;
}

// <== THE BOOK'S OWN DESIGN (a safe subset) ==>
// The server sends the book's structural styling, filtered and scoped to
// #chapter-content (see utils.book_style_subset): centred titles, italics,
// small caps, poem indents, relative sizes.
function applyBookStyle(css) {
    let el = document.getElementById('book-style');
    if (!el) {
        el = document.createElement('style');
        el.id = 'book-style';
        document.head.appendChild(el);
    }
    el.textContent = css || '';
}

// After a chapter renders:
// - Books pad between blocks with "blank" ones (<div>&nbsp;<br></div>). The
//   reader already spaces paragraphs, so those add a second, uneven gap: mark
//   them so CSS can drop them. (CSS alone can't see that &nbsp; is blank.)
// - Short blocks the book sets noticeably larger than its body text are
//   headings ("II", "Retribution"), even when they're plain <div>s: mark them
//   so they get heading weight and spacing.
// Paginated mode lays out a whole chapter as columns at once, so every image's
// size must be known: lazy images (sized 0 until scrolled to) would load as
// you turn pages and push the text along, changing the page count under you.
// Load them all now, and re-lay out (keeping your place) as each arrives.
let _imageRelayoutTimer = null;
function watchChapterImages(root) {
    root.querySelectorAll('img').forEach((img) => {
        if (isPaginated()) img.loading = 'eager';
        if (img.complete) return;
        img.addEventListener('load', () => {
            if (!isPaginated()) return;
            clearTimeout(_imageRelayoutTimer);
            _imageRelayoutTimer = setTimeout(() => relayoutPreservingPosition(), 120);
        }, {once: true});
    });
}

// Vertical text: a number of one or two digits stands upright in one cell
// ("第1段", "12月"), as in print; longer numbers and Latin words run sideways.
// (text-combine-upright: digits 2 would do this alone, but few browsers have it.)
function uprightDigits(root) {
    const digits = /(?<![0-9A-Za-z.,])[0-9]{1,2}(?![0-9A-Za-z]|[.,][0-9])/g;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (n) => (n.parentElement.closest('script, style, .tcy') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) if (/[0-9]/.test(n.data)) nodes.push(n);
    for (const n of nodes) {
        const parts = [];
        let last = 0;
        for (const m of n.data.matchAll(digits)) {
            if (m.index > last) parts.push(n.data.slice(last, m.index));
            const cell = document.createElement('span');
            cell.className = 'tcy';
            cell.textContent = m[0];
            parts.push(cell);
            last = m.index + m[0].length;
        }
        if (!last) continue;
        if (last < n.data.length) parts.push(n.data.slice(last));
        n.replaceWith(...parts);
    }
}

function tidyChapter(root) {
    if (isVertical()) uprightDigits(root);
    const base = parseFloat(getComputedStyle(root).fontSize) || 16;
    root.querySelectorAll('p, div, h1, h2, h3, h4, h5, h6').forEach((el) => {
        const text = el.textContent.trim();
        if (!text) {
            if (!el.querySelector('img, svg, image, hr, table, figure')) el.classList.add('reader-spacer');
            return;
        }
        if (text.length > 120 || el.querySelector('p, div')) return;
        const size = parseFloat(getComputedStyle(el).fontSize) || base;
        if (/^H[1-6]$/.test(el.tagName) || size >= base * 1.08) el.classList.add('reader-heading');
    });
    // A heading before any running text opens the chapter: give it room.
    const firstText = Array.from(root.querySelectorAll(':is(p, div):not(:has(p, div))'))
        .find((el) => el.textContent.trim().length > 200);
    const opener = root.querySelector('.reader-heading');
    if (opener && (!firstText || (opener.compareDocumentPosition(firstText) & Node.DOCUMENT_POSITION_FOLLOWING))) {
        opener.classList.add('chapter-opening');
    }
}

// Whole-book progress in [0, 1]: chapters weighted by size, matching the
// server's utils.book_progress so the % under the library's covers agrees.
function bookProgressFraction() {
    const sizes = (currentBook && currentBook.chapter_sizes) || [];
    const total = sizes.reduce((a, b) => a + b, 0);
    if (!total) return 0;
    const idx = Math.max(0, Math.min(currentChapterNum, sizes.length - 1));
    const before = sizes.slice(0, idx).reduce((a, b) => a + b, 0);
    const pos = Math.max(0, Math.min(1, currentPositionFraction()));
    return Math.max(0, Math.min(1, (before + pos * sizes[idx]) / total));
}

// Spine index -> the table of contents' name for it. The TOC names are the
// publisher's; titles scraped from chapter HTML are often the book's title.
let tocTitles = {};
function indexTocTitles(entries) {
    for (const entry of entries || []) {
        if (entry.spine_index >= 0 && !(entry.spine_index in tocTitles) && !entry.synthetic) {
            tocTitles[entry.spine_index] = entry.title;
        }
        indexTocTitles(entry.children);
    }
}

function updateChapterNumberLabel() {
    if (!currentBook) return;
    const head = document.getElementById('running-head');
    const foot = document.getElementById('running-foot');
    const chapter = allChapters[currentChapterNum];
    const title = tocTitles[currentChapterNum] || tocTitles[chapterStart(currentChapterNum)]
        || (chapter && chapter.title) || `Section ${currentChapterNum + 1}`;
    const pct = Math.floor(bookProgressFraction() * 100);
    // The chapter in the top margin, time left in the bottom one, like a
    // book's running head and folio. "in chapter" drops on phones (CSS).
    head.textContent = title;
    alignRunningLines();
    const left = timeLeft();
    foot.innerHTML = left
        ? `${formatMinutes(left.chapter)} left<span class="running-long"> in chapter</span> · ${formatMinutes(left.book)} in book`
        : `${pct}%`;
    foot.title = `${pct}% through the book · section ${currentChapterNum + 1} of ${currentBook.spine_length}`
        + (left ? ` · at ${Math.round(readingSpeed())} words a minute` : '');
}

function nextPage() {
    if (!currentBook) return;
    if (currentPageIndex < totalPages - 1) {
        currentPageIndex++;
        applyPageTransform(true);
        updateProgressBar();
        updateChapterNumberLabel();
        saveBookmark();
        maybeOfferFinished();
    } else {
        nextChapter();
    }
}

function prevPage() {
    if (!currentBook) return;
    if (currentPageIndex > 0) {
        currentPageIndex--;
        applyPageTransform(true);
        updateProgressBar();
        updateChapterNumberLabel();
        saveBookmark();
    } else {
        prevChapter();
    }
}

function toggleReadingMode() {
    if (!currentBook || isVertical()) return;   // vertical text is always in pages
    // Capture position before switching so we can land on roughly the same
    // content in the new mode.
    const fraction = currentPositionFraction();
    readingMode = isPaginated() ? 'scroll' : 'paginate';
    localStorage.setItem('readingMode', readingMode);
    applyReadingModeClass();
    updateReadingModeButton();

    if (isPaginated()) {
        // Clear stray scroll position so the page columns line up cleanly.
        jumpScroll(0);
        requestAnimationFrame(() => relayoutPreservingPosition(fraction));
    } else {
        // Reset column scroll so going back into paginate mode later isn't
        // sticky if user had it half-scrolled.
        const content = document.getElementById('chapter-content');
        if (content) content.scrollLeft = 0;
        requestAnimationFrame(() => {
            jumpScroll(fraction * document.documentElement.scrollHeight);
            updateProgressBar();
            updateChapterNumberLabel();
        });
    }
}

function currentPositionFraction() {
    if (isPaginated()) {
        return totalPages > 1 ? currentPageIndex / (totalPages - 1) : 0;
    }
    const sh = document.documentElement.scrollHeight;
    return sh > 0 ? window.scrollY / sh : 0;
}


document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');

// Initialize overlay and event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Add overlay HTML
    const overlay = document.createElement('div');
    overlay.className = 'search-overlay';
    overlay.innerHTML = `
        <div class="search-container">
            <div class="search-input-container">
                <input type="text" class="search-input" placeholder="Ask about this…" aria-label="Ask about the selected text">
            </div>
            <div class="search-response-container">
                <div class="search-response"></div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Add selection menu
    const selectionMenu = document.createElement('div');
    selectionMenu.className = 'selection-menu';
    // Two actions: Ask (type a question) and Explain (define a word,
    // translate foreign text, or gloss a passage — the server picks).
    selectionMenu.innerHTML = `
        <button class="ask-button" title="Ask about this (A)">
            ${icon('message-circle')}<span>Ask</span>
        </button>
        <button class="explain-button" title="Explain this (E)">
            ${icon('lightbulb')}<span>Explain</span>
        </button>
    `;
    document.body.appendChild(selectionMenu);
    // Keep the text selected while pressing a menu button.
    selectionMenu.addEventListener('mousedown', (e) => e.preventDefault());

    // Handle all mouse events at the document level
    document.addEventListener('mousedown', (e) => {
        const overlay = document.querySelector('.search-overlay');
        // Only handle close if overlay is active
        if (overlay.classList.contains('active') && 
            !overlay.contains(e.target) && 
            e.target.tagName !== 'INPUT') {
            closeOverlay();
        }
    });

    // Handle overlay input
    document.querySelector('.search-input').addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' || e.key === 'Escape') {
            if (e.key === 'Escape') {
                closeOverlay();
            } else if (e.key === 'Enter') {
                const userInput = e.target.value.trim();

                // Get the highlighted text from the temp-highlight span
                const tempHighlight = document.querySelector('.temp-highlight');
                const highlightedText = tempHighlight ? tempHighlight.textContent.trim() : '';

                // Start loading animation immediately
                const container = document.querySelector('.search-container');
                const responseContainer = document.querySelector('.search-response-container');
                const responseElement = document.querySelector('.search-response');
                responseContainer.classList.add('active');
                responseElement.className = 'thinking-animation';
                responseElement.textContent = 'Thinking';
                
                try {
                    const response = await fetch(appUrl('/ask_question'), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            context: highlightedText,
                            question: userInput
                        })
                    });

                    const data = await response.json().catch(() => ({}));
                    showAiResult(data.answer, data.error);
                } catch (error) {
                    console.error('Error getting answer:', error);
                    showAiResult(null, "Couldn't reach the library. Check your connection.");
                }
            }
        }
    });

    // Handle keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // With text selected: A asks, E explains (D and L, the old define and
        // translate keys, explain too). No modifier, so the browser's own ⌘D
        // (bookmark) and ⌘L (address bar) keep working.
        if (e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target)) return;
        const key = e.key.toLowerCase();
        if (key === 'a' || key === 'e' || key === 'd' || key === 'l') {
            const selection = window.getSelection();
            const selectedString = selection.toString().trim();
            if (!selection.rangeCount || !selectedString) return;
            e.preventDefault();
            
            // Store the selected range and create highlight
            selectedRange = selection.getRangeAt(0).cloneRange();
            const tempHighlight = wrapRangeInHighlight(selectedRange);
            if (!tempHighlight) return;

            document.querySelector('.selection-menu')?.classList.remove('active');
            if (key === 'a') {
                initializeOverlay(tempHighlight, 'question');
            } else {
                initializeOverlay(tempHighlight, 'explanation');
                handleExplainRequest(selectedString, tempHighlight);
            }
        }
    });

    // Toggle menu visibility
    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            const menu = document.getElementById('toc-menu');
            menu.classList.toggle('visible');
            // Open at the chapter you're in, not at the top of a long list.
            if (menu.classList.contains('visible')) {
                menu.querySelector('.toc-item.active')?.scrollIntoView({block: 'center'});
            }
        });
    }

    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
        const menu = document.getElementById('toc-menu');
        const menuToggle = document.getElementById('menu-toggle');
        
        if (menu && menuToggle && !menu.contains(e.target) && !menuToggle.contains(e.target) && menu.classList.contains('visible')) {
            menu.classList.remove('visible');
        }
    });

    // Show Ask / Explain next to any selection in the book (touch and mouse).
    document.addEventListener('selectionchange', () => {
        const selection = window.getSelection();
        const selectionMenu = document.querySelector('.selection-menu');
        const selectedString = selection.toString().trim();
        const inBook = selection.rangeCount
            && document.getElementById('chapter-content').contains(selection.getRangeAt(0).commonAncestorContainer);

        if (!selection.rangeCount || !selectedString || !inBook) {
            selectionMenu.classList.remove('active');
            return;
        }

        // Position menu above selection with more offset to avoid native menu
        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        selectionMenu.style.top = `${window.scrollY + rect.bottom + 10}px`;
        const menuWidth = selectionMenu.offsetWidth || 150; // Fallback width if not yet rendered
        selectionMenu.style.left = `${Math.max(10, Math.min(window.innerWidth - menuWidth - 10, rect.left))}px`;
        
        selectionMenu.classList.add('active');
        selectedRange = range.cloneRange();

        // Add click handlers to buttons
        document.querySelector('.ask-button').onclick = () => handleSelectionAction('question');
        document.querySelector('.explain-button').onclick = () => handleSelectionAction('explanation');
    });

    // Handle selection menu actions
    function handleSelectionAction(action) {
        // Use the range saved when the menu appeared: clicking a button can
        // clear the live selection first.
        if (!selectedRange) return;
        const selectedString = selectedRange.toString().trim();
        if (!selectedString) return;

        // Create highlight
        const tempHighlight = wrapRangeInHighlight(selectedRange);
        if (!tempHighlight) return;

        // Initialize overlay and handle action
        initializeOverlay(tempHighlight, action);
        if (action === 'explanation') {
            handleExplainRequest(selectedString, tempHighlight);
        }

        // Hide the selection menu
        document.querySelector('.selection-menu').classList.remove('active');
    }
});

// <== READING POSITION ==>
// The last position is also kept on this device, so reading offline (or
// through a failed save) never loses your place. `pending` marks a position
// the server hasn't confirmed yet; it's resent when the connection returns.
const POSITION_KEY = `position:${filename}`;

function readLocalPosition() {
    try { return JSON.parse(localStorage.getItem(POSITION_KEY)); } catch { return null; }
}

function writeLocalPosition(pos) {
    try { localStorage.setItem(POSITION_KEY, JSON.stringify(pos)); } catch { /* storage full or blocked */ }
}

async function fetchWithTimeout(url, ms, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
        return await fetch(url, {...options, signal: controller.signal});
    } finally {
        clearTimeout(timer);
    }
}

// Where to open the book: an unsynced local position wins (it's newer than
// anything the server has), then the server's bookmark, then any local one.
async function resolveStartPosition() {
    const local = readLocalPosition();
    if ((local && local.pending) || !window.IS_AUTHENTICATED) return local;
    try {
        const r = await fetchWithTimeout(appUrl(`/bookmark/${filename}`), 2000);
        if (r.ok) {
            const d = await r.json();
            if ('chapter_index' in d) return {chapter: d.chapter_index, position: d.position};
        }
    } catch { /* offline or slow: fall through */ }
    return local;
}

// <== LOADING THE BOOK ==>
function showLoadError(message) {
    document.getElementById('loading-spinner').style.display = 'none';
    document.getElementById('reader-content').style.display = 'block';
    const box = document.getElementById('chapter-content');
    box.replaceChildren();
    const card = document.createElement('div');
    card.className = 'reader-message';
    const p = document.createElement('p');
    p.textContent = message;
    const actions = document.createElement('div');
    actions.className = 'reader-message__actions';
    const back = document.createElement('a');
    back.className = 'btn btn-secondary';
    back.href = appUrl('/');
    back.textContent = 'Back to library';
    const retry = document.createElement('button');
    retry.className = 'btn btn-secondary';
    retry.textContent = 'Try again';
    retry.addEventListener('click', () => location.reload());
    actions.append(back, retry);
    card.append(p, actions);
    box.append(card);
}

window.addEventListener('DOMContentLoaded', async () => {
    document.getElementById('loading-spinner').style.display = 'block';

    const start = await resolveStartPosition();

    let response;
    try {
        // ?v= keys the offline copy to this version of the EPUB (sw.js).
        response = await fetch(appUrl(`/load_book/${filename}?v=${window.BOOK_VERSION || 0}`));
    } catch (err) {
        console.error('Error fetching book:', err);
        showLoadError(navigator.onLine
            ? "This book couldn't be opened. Check your connection and try again."
            : "This book isn't saved on this device yet. Open it once while online to read it offline.");
        return;
    }
    if (!response.ok) {
        showLoadError(response.status === 404
            ? 'This book is no longer in the library.'
            : "This book couldn't be opened.");
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = '';

    function processChunk(chunk) {
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop(); // Keep the last incomplete line

        for (const line of lines) {
            if (!line.trim()) continue;

            const data = JSON.parse(line);
            switch (data.type) {
                case 'metadata':
                    currentBook = data;
                    applyBookStyle(data.book_css);
                    currentChapterNum = start ? start.chapter : currentBook.start_chapter;
                    currentPagePosition = start ? start.position : currentBook.chapter_pos;
                    if (!(currentChapterNum >= 0 && currentChapterNum < currentBook.spine_length)) {
                        currentChapterNum = 0;
                        currentPagePosition = 0;
                    }
                    displayBookMetadata();
                    break;
                case 'chapter':
                    currentChapter = data;
                    const chapterNum = currentChapter.index;
                    hrefChapterMapping[currentChapter.href] = chapterNum;

                    // Ungrey every TOC entry pointing at this spine index, and
                    // for synthetic entries (no real NCX) replace the placeholder
                    // title with the one scraped from the chapter HTML.
                    document.querySelectorAll(
                        `#toc-content .toc-item[data-spine-index="${chapterNum}"]`
                    ).forEach(item => {
                        item.classList.remove('unprocessed');
                        if (item.dataset.synthetic === 'true' && currentChapter.title) {
                            item.textContent = currentChapter.title;
                        }
                    });

                    allChapters[chapterNum] = currentChapter;
                    if (chapterNum == currentChapterNum) {
                        document.getElementById('loading-spinner').style.display = 'none';
                        document.getElementById('reader-content').style.display = 'block';
                        applyReadingModeClass();
                        updateReadingModeButton();
                        displayChapter();

                        // Wait for next paint to ensure content is rendered
                        requestAnimationFrame(() => {
                            if (isPaginated()) {
                                relayoutPreservingPosition(currentPagePosition);
                            } else {
                                jumpScroll(currentPagePosition * document.documentElement.scrollHeight);
                            }
                            updateChapterNumberLabel();
                            if (currentPagePosition > 0.01) setTimeout(markYourPlace, 250);
                        });
                    }
                    break;
                case 'error':
                    console.error('Error streaming book:', data.message);
                    if (!allChapters[currentChapterNum]) {
                        showLoadError("This book couldn't be opened. The file may be damaged.");
                    }
                    break;
            }
        }
    }
    function readStream() {
        reader.read().then(({done, value}) => {
            if (done) {
                if (buffer) {
                    processChunk('\n');
                }
                return;
            }
            processChunk(decoder.decode(value, {stream: true}));
            readStream();
        }).catch(error => {
            console.error('Error reading stream:', error);
            if (!allChapters[currentChapterNum]) {
                showLoadError("This book couldn't be opened. Check your connection and try again.");
            }
        });
    }
    readStream();
});

function displayBookMetadata() {
    document.title = currentBook.title;
    document.getElementById('book-title').textContent = currentBook.title;
    document.getElementById('book-author').textContent = currentBook.author || 'Unknown author';

    const tocContent = document.getElementById('toc-content');
    tocContent.replaceChildren(buildTocList(currentBook.toc || []));
    tocTitles = {};
    indexTocTitles(currentBook.toc);
    highlightActiveTocItem();
}

function buildTocList(entries) {
    const ol = document.createElement('ol');
    ol.className = 'toc-list';
    for (const entry of entries) {
        const li = document.createElement('li');
        const item = document.createElement('div');
        item.className = 'toc-item';
        item.textContent = entry.title;
        if (entry.spine_index >= 0) {
            item.dataset.spineIndex = entry.spine_index;
            if (entry.section_id) item.dataset.sectionId = entry.section_id;
            if (entry.synthetic) item.dataset.synthetic = 'true';
            // Until the chapter content arrives, the click target is unusable
            if (!allChapters[entry.spine_index]) item.classList.add('unprocessed');
            item.addEventListener('click', () => {
                jumpToChapter(entry.spine_index, entry.section_id);
            });
        } else {
            item.classList.add('toc-section-header');
        }
        li.appendChild(item);
        if (entry.children && entry.children.length) {
            li.appendChild(buildTocList(entry.children));
        }
        ol.appendChild(li);
    }
    return ol;
}

function highlightActiveTocItem() {
    document.querySelectorAll('#toc-content .toc-item').forEach(item => {
        const idx = parseInt(item.dataset.spineIndex, 10);
        item.classList.toggle('active', idx === currentChapterNum);
    });
}

function updateProgressBar() {
    let position;
    if (isPaginated()) {
        position = totalPages > 1 ? currentPageIndex / (totalPages - 1) : 0;
    } else {
        const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
        position = scrollHeight > 0 ? Math.min(1, window.scrollY / scrollHeight) : 0;
    }
    document.getElementById('chapter-progress').style.width = `${position * 100}%`;
}

function currentBookmark() {
    return {chapter_index: currentChapterNum, position: currentPositionFraction()};
}

function postBookmark(body) {
    return fetch(appUrl(`/bookmark/${filename}`), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const local = readLocalPosition();
        // Only clear the flag if nothing newer was recorded meanwhile.
        if (local && local.chapter === body.chapter_index && local.position === body.position) {
            writeLocalPosition({...local, pending: false});
        }
    });
}

function saveBookmark() {
    if (!lastSaveTimeout) {
        lastSaveTimeout = setTimeout(() => {
            const body = currentBookmark();
            // Signed out: the position lives on this device only.
            writeLocalPosition({chapter: body.chapter_index, position: body.position,
                                pending: Boolean(window.IS_AUTHENTICATED)});
            if (window.IS_AUTHENTICATED) {
                postBookmark(body).catch(error => console.warn('Position saved on this device only:', error));
            }
            lastSaveTimeout = null;
        }, 1000); // Debounce save for 1 second
    }
}

// Resend a position that was saved while offline.
window.addEventListener('online', () => {
    const local = readLocalPosition();
    if (local && local.pending) {
        postBookmark({chapter_index: local.chapter, position: local.position}).catch(() => {});
    }
});

// Leaving the page can cancel the debounced save; record the final position
// locally and send it with a beacon, which survives navigation.
window.addEventListener('pagehide', () => {
    if (!currentBook || !window.IS_AUTHENTICATED) {
        if (currentBook) {
            const body = currentBookmark();
            writeLocalPosition({chapter: body.chapter_index, position: body.position, pending: false});
        }
        return;
    }
    const body = currentBookmark();
    writeLocalPosition({chapter: body.chapter_index, position: body.position, pending: true});
    const blob = new Blob([JSON.stringify(body)], {type: 'application/json'});
    if (navigator.sendBeacon && navigator.sendBeacon(appUrl(`/bookmark/${filename}`), blob)) {
        // Beacons can't report success; a later successful save clears the flag.
    }
});

function displayChapter() {
    const content = allChapters[currentChapterNum].content;
    const chapterEl = document.getElementById('chapter-content');
    chapterEl.innerHTML = content;
    // Its language (for reading aloud): the chapter's own, else the book's.
    chapterEl.lang = allChapters[currentChapterNum].lang || currentBook?.language || '';
    applyReadingModeClass();   // an untagged book is known to be Chinese only from its text
    chapterEl.classList.toggle('cjk', isCjkChapter());   // set in a Chinese serif (reader.css)
    tidyChapter(chapterEl);
    watchChapterImages(chapterEl);

    addChapterEnd(chapterEl);

    if (isPaginated()) {
        currentPageIndex = 0;
        layoutPaginatedChapter();
    }
    updateChapterNumberLabel();
    updateProgressBar();
}

function nextChapter() {
    if (currentChapterNum < currentBook.spine_length - 1) {
        currentChapterNum++;
        displayChapter();
        if (isPaginated()) {
            currentPageIndex = 0;
            applyPageTransform(false);
        } else {
            jumpScroll(0);
        }
        updateProgressBar();
        updateChapterNumberLabel();
        highlightActiveTocItem();
        saveBookmark();
    }

    maybeOfferFinished();
}

// Near the end, offer to mark the book finished instead of deciding for you:
// the last sections are often notes or an index, read or not.
const FINISH_OFFER_AT = 0.9;
let _finishOffered = false;
function maybeOfferFinished() {
    if (_finishOffered || !currentBook || !window.IS_AUTHENTICATED) return;
    if (bookProgressFraction() < FINISH_OFFER_AT) return;
    _finishOffered = true;
    const offer = document.createElement('div');
    offer.className = 'finish-offer';
    offer.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.textContent = `Finished ${currentBook.title}?`;
    const yes = document.createElement('button');
    yes.type = 'button';
    yes.className = 'btn btn-secondary';
    yes.textContent = 'Mark as finished';
    yes.addEventListener('click', async () => {
        yes.disabled = true;
        try {
            const r = await fetch(appUrl(`/tag_finished/${filename}`), {method: 'POST'});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            text.textContent = 'Marked as finished.';
            yes.remove();
            setTimeout(() => offer.remove(), 2500);
        } catch {
            text.textContent = "Couldn't save that. Try again.";
            yes.disabled = false;
        }
    });
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'finish-offer__dismiss';
    dismiss.setAttribute('aria-label', 'Not yet');
    dismiss.innerHTML = icon('x');
    dismiss.addEventListener('click', () => offer.remove());
    offer.append(text, yes, dismiss);
    document.body.append(offer);
}

// Back a chapter. Turning back past a chapter's first page (or scrolling
// past its top) lands at the end of the one before, like a book; Shift+←
// (toStart) jumps to its beginning, matching Shift+→.
function prevChapter(toStart = false) {
    if (currentChapterNum > 0) {
        currentChapterNum--;
        displayChapter();
        if (isPaginated()) {
            currentPageIndex = toStart ? 0 : Math.max(0, totalPages - 1);
            applyPageTransform(false);
        } else {
            jumpScroll(toStart ? 0 : document.body.scrollHeight);
        }
        updateProgressBar();
        updateChapterNumberLabel();
        highlightActiveTocItem();
        saveBookmark();
    }
}

function jumpToChapter(index, sectionId) {
    if (index < 0 || !allChapters[index]) return;
    resetSpeedBaseline();   // a jump isn't reading
    currentChapterNum = index;
    displayChapter();

    if (isPaginated()) {
        requestAnimationFrame(() => {
            if (sectionId) {
                const target = document.getElementById(sectionId);
                currentPageIndex = target ? pageOfElement(target) : 0;
            } else {
                currentPageIndex = 0;
            }
            applyPageTransform(false);
            updateProgressBar();
            updateChapterNumberLabel();
        });
    } else if (sectionId) {
        requestAnimationFrame(() => {
            const target = document.getElementById(sectionId);
            if (target) {
                const offset = currentFontSize * 2;
                jumpScroll(window.pageYOffset + target.getBoundingClientRect().top - offset);
            } else {
                jumpScroll(0);
            }
        });
    } else {
        jumpScroll(0);
    }

    updateProgressBar();
    document.getElementById('toc-menu').classList.remove('visible');
    highlightActiveTocItem();
    saveBookmark();
}

function adjustFontSize(delta) {
    currentFontSize = Math.max(12, Math.min(24, currentFontSize + delta));
    document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');
    localStorage.setItem('readerFontSize', currentFontSize);
    if (isPaginated()) relayoutPreservingPosition();
    syncSettingsPanel();
}

window.addEventListener('scroll', () => {
    updateProgressBar();
    updateChapterNumberLabel();
    saveBookmark();
    maybeOfferFinished();
});

const HOVER_CAPABLE = window.matchMedia('(hover: hover)').matches;

// The top bar floats over the page and is hidden until you reach for it:
// the mouse at the top edge (CSS), a tap in the middle of the page, or the
// contents panel. It never changes the page's layout.
function applyChrome(show) {
    const bar = document.querySelector('.top-controls');
    if (!show && bar.classList.contains('pinned')) return;   // the Aa panel is open
    bar.classList.toggle('visible', show);
    document.documentElement.classList.toggle('bar-visible', show);
}

function isChromeVisible() {
    return document.querySelector('.top-controls').classList.contains('visible');
}

// Programmatic jumps (bookmark restore, chapter/TOC nav, mode switch) must
// not read as scroll gestures to the bar policy — the bars would show or
// hide depending on which direction the jump happened to go.
let _ignoreScroll = false;
function jumpScroll(top) {
    _ignoreScroll = true;
    window.scrollTo({top, behavior: 'instant'});
}

// Desktop: the pointer at the top edge brings the bar down; moving well down
// into the text sends it away (unless the Aa panel or contents are open).
// The pointer itself hides after a moment of stillness.
if (HOVER_CAPABLE) {
    let idle = null, lastX = null, lastY = null;
    document.addEventListener('mousemove', (e) => {
        // Browsers also fire this when the page moves under a still pointer.
        if (e.clientX === lastX && e.clientY === lastY) return;
        const first = lastX === null;
        lastX = e.clientX; lastY = e.clientY;
        if (first) return;   // where the pointer happened to be at load
        const bar = document.querySelector('.top-controls');
        if (e.clientY < 28) applyChrome(true);
        else if (e.clientY > bar.offsetHeight + 60 && !bar.contains(e.target)
                 && !document.getElementById('toc-menu')?.classList.contains('visible')) applyChrome(false);
        document.documentElement.classList.remove('pointer-idle');
        clearTimeout(idle);
        idle = setTimeout(() => document.documentElement.classList.add('pointer-idle'), 2000);
    }, {passive: true});
}


// True when a key press is going into a text field (so shortcuts stay out of it).
function isTypingTarget(target) {
    return Boolean(target && target.closest && target.closest('input, textarea, select, [contenteditable]'));
}

// <== PAGINATED MODE: input + lifecycle ==>
// Plain arrows = a page (paginated) or a screen (scroll). Shift+arrows =
// section jump. Never steals keys from inputs or modified shortcuts.
// T contents, +/- text size, N night, Esc closes whatever is open, ? help.
document.addEventListener('keydown', (e) => {
    if (isTypingTarget(e.target)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === 'Escape') {
        const toc = document.getElementById('toc-menu');
        if (document.querySelector('.shortcut-help')) closeShortcutHelp();
        else if (document.querySelector('.search-overlay.active')) closeOverlay();
        else if (toc.classList.contains('visible')) toc.classList.remove('visible');
        return;
    }
    const hasSelection = Boolean(window.getSelection().toString().trim());
    if (!e.shiftKey && !hasSelection) {
        const k = e.key.toLowerCase();
        if (k === 't') { e.preventDefault(); document.getElementById('menu-toggle').click(); return; }
        if (k === 'n') { e.preventDefault(); toggleNight(); return; }
    }
    if (e.key === '+' || e.key === '=') { e.preventDefault(); adjustFontSize(1); return; }
    if (e.key === '-' || e.key === '_') { e.preventDefault(); adjustFontSize(-1); return; }
    if (e.key === '?') { e.preventDefault(); toggleShortcutHelp(); return; }

    // Vertical books turn the other way: ← is onwards, as in a printed one.
    const forward = isVertical() ? 'ArrowLeft' : 'ArrowRight';
    const back = isVertical() ? 'ArrowRight' : 'ArrowLeft';
    if (e.shiftKey) {
        if (e.key === forward) {
            e.preventDefault();
            nextChapter();
        } else if (e.key === back) {
            e.preventDefault();
            prevChapter(true);
        }
        return;
    }

    if (!isPaginated()) {
        // Scroll mode: arrows move a screen, keeping a couple of lines of overlap.
        // At the end of a chapter → goes on to the next; at the top ← goes back.
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            const atEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
            if (e.key === 'ArrowRight' && atEnd) { nextChapter(); return; }
            if (e.key === 'ArrowLeft' && window.scrollY <= 4) { prevChapter(); return; }
            const step = window.innerHeight * 0.85;
            window.scrollBy({top: e.key === 'ArrowRight' ? step : -step, behavior: 'smooth'});
        }
        return;
    }
    if (e.key === forward || e.key === 'PageDown' || e.key === ' ') {
        e.preventDefault();
        nextPage();
    } else if (e.key === back || e.key === 'PageUp') {
        e.preventDefault();
        prevPage();
    }
});

const SHORTCUTS = [
    ['← →', 'Previous / next page'],
    ['Shift + ← →', 'Previous / next section'],
    ['T', 'Contents'],
    ['+ −', 'Text size'],
    ['N', 'Night mode'],
    ['L', 'Read aloud: start or pause'],
    ['A', 'Ask about the selected text'],
    ['E', 'Explain it: define, translate or gloss'],
    ['Esc', 'Close'],
    ['?', 'Show these shortcuts'],
];

function toggleShortcutHelp() {
    if (document.querySelector('.shortcut-help')) return closeShortcutHelp();
    const sheet = document.createElement('div');
    sheet.className = 'shortcut-help';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', 'Keyboard shortcuts');
    const list = document.createElement('dl');
    for (const [keys, what] of SHORTCUTS) {
        const dt = document.createElement('dt');
        keys.split(' ').forEach((k, i) => {
            if (i) dt.append(' ');
            // The "+" in "Shift + ←" joins keys; elsewhere it's a key.
            if (k === '+' && keys.startsWith('Shift')) { dt.append(k); return; }
            const kbd = document.createElement('kbd');
            kbd.textContent = k;
            dt.append(kbd);
        });
        const dd = document.createElement('dd');
        dd.textContent = what;
        list.append(dt, dd);
    }
    sheet.append(list);
    sheet.addEventListener('click', closeShortcutHelp);
    document.body.append(sheet);
}

function closeShortcutHelp() {
    document.querySelector('.shortcut-help')?.remove();
}

// Interactive chrome that page-level clicks, taps, and swipes ignore.
const CHROME_SELECTOR =
    'button, a, input, textarea, .toc-menu, .top-controls, ' +
    '.selection-menu, .search-overlay, .temp-highlight, .note-popover, .back-pill, .reader-settings, ' +
    '.finish-offer, .shortcut-help, .read-aloud';

// Click left third of the reader to go back a page, right third forward.
// Middle third is a no-op so text selection still works freely.
document.addEventListener('click', (e) => {
    if (!isPaginated()) return;
    // Don't trigger when clicking interactive chrome or the user has text
    // selected (probably trying to use the selection menu).
    if (e.target.closest(CHROME_SELECTOR)) return;
    if (window.getSelection().toString().trim()) return;

    // A vertical book's next page is on the left.
    const w = window.innerWidth;
    if (e.clientX < w * 0.35) {
        if (isVertical()) nextPage(); else prevPage();
    } else if (e.clientX > w * 0.65) {
        if (isVertical()) prevPage(); else nextPage();
    }
});

// <== HORIZONTAL SWIPE: page turn (paginated mode only) ==>
// Vertical-dominant gestures fall through to normal scrolling, and an active
// text selection suppresses nav so the selection menu stays usable.
const SWIPE_MIN_PX = 70;        // ignore short drags
let _swipeStartX = null, _swipeStartY = null;
document.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) { _swipeStartX = null; return; }
    // Ignore swipes that start on interactive chrome.
    if (e.target.closest(CHROME_SELECTOR)) { _swipeStartX = null; return; }
    _swipeStartX = e.touches[0].clientX;
    _swipeStartY = e.touches[0].clientY;
}, {passive: true});
document.addEventListener('touchend', (e) => {
    if (_swipeStartX === null) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - _swipeStartX;
    const dy = t.clientY - _swipeStartY;
    _swipeStartX = null;
    // Require a clearly horizontal swipe past the threshold.
    if (Math.abs(dx) < SWIPE_MIN_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    if (window.getSelection().toString().trim()) return;
    // Paginated only: in scroll mode a slightly diagonal scroll would jump a
    // whole section. The bottom bar's buttons change section there.
    if (!isPaginated()) return;
    // Pull the page across as in a book: leftwards onwards, or rightwards in a vertical one.
    if ((dx < 0) !== isVertical()) nextPage(); else prevPage();
}, {passive: true});

// <== BARS: hide on scroll down, show near the top, tap to toggle ==>
let _lastScrollY = window.scrollY;
window.addEventListener('scroll', () => {
    const y = window.scrollY;
    if (_ignoreScroll) { _ignoreScroll = false; _lastScrollY = y; return; }
    if (y > _lastScrollY && y > 100) applyChrome(false);
    _lastScrollY = y;
}, {passive: true});

// A clean tap toggles both bars (no hover on phones to summon them back).
// In paginated mode the side zones stay page-turn only, and toggling
// relayouts, since the bars' reserved padding shapes the page.
const TAP_MAX_PX = 10, TAP_MAX_MS = 350;
let _tapStart = null;
document.addEventListener('touchstart', (e) => {
    _tapStart = e.touches.length === 1
        ? {x: e.touches[0].clientX, y: e.touches[0].clientY, t: e.timeStamp}
        : null;
}, {passive: true});
document.addEventListener('touchend', (e) => {
    if (!_tapStart) return;
    const start = _tapStart;
    _tapStart = null;
    const touch = e.changedTouches[0];
    if (Math.abs(touch.clientX - start.x) > TAP_MAX_PX ||
        Math.abs(touch.clientY - start.y) > TAP_MAX_PX ||
        e.timeStamp - start.t > TAP_MAX_MS) return;
    if (e.target.closest(CHROME_SELECTOR)) return;
    // A tap that dismisses something open shouldn't also toggle the bars.
    if (document.getElementById('toc-menu')?.classList.contains('visible')) return;
    if (document.querySelector('.search-overlay')?.classList.contains('active')) return;
    if (window.getSelection().toString().trim()) return;
    if (isPaginated() &&
        (touch.clientX < window.innerWidth * 0.35 || touch.clientX > window.innerWidth * 0.65)) return;

    applyChrome(!isChromeVisible());
}, {passive: true});

// Recompute pagination on resize. Debounced; preserves the user's relative
// position in the chapter across the relayout.
let _readerResizeTimer;
window.addEventListener('resize', () => {
    if (!isPaginated()) return;
    clearTimeout(_readerResizeTimer);
    _readerResizeTimer = setTimeout(relayoutPreservingPosition, 150);
});

// Reflect the persisted mode in the toggle button as soon as the DOM is ready,
// before the book has streamed in.
document.addEventListener('DOMContentLoaded', () => {
    applyReadingModeClass();
    updateReadingModeButton();
});

// surroundContents throws if the selection straddles element boundaries.
// Fall back to extractContents/insertNode, which always works.
function wrapRangeInHighlight(range) {
    const span = document.createElement('span');
    span.className = 'temp-highlight';
    try {
        range.surroundContents(span);
    } catch (_) {
        try {
            span.appendChild(range.extractContents());
            range.insertNode(span);
        } catch (err) {
            console.error('Could not wrap selection:', err);
            return null;
        }
    }
    return span;
}

// Update the closeOverlay function
function closeOverlay() {
    const overlay = document.querySelector('.search-overlay');
    const container = document.querySelector('.search-container');
    const responseElement = document.querySelector('.search-response');
    
    overlay.classList.remove('active');
    container.classList.remove('expanded');
    document.querySelector('.search-response-container').classList.remove('active');
    responseElement.textContent = '';
    
    // Remove temporary highlight
    const tempHighlight = document.querySelector('.temp-highlight');
    if (tempHighlight) {
        const parent = tempHighlight.parentNode;
        while (tempHighlight.firstChild) {
            parent.insertBefore(tempHighlight.firstChild, tempHighlight);
        }
        parent.removeChild(tempHighlight);
    }
    
    // Clear the stored range
    selectedRange = null;
}

// Phones: the AI box is a bottom sheet instead of a popover. Keep it above the
// on-screen keyboard by tracking the visual viewport.
const SHEET_QUERY = window.matchMedia('(max-width: 640px)');
function positionSheetAboveKeyboard() {
    const overlay = document.querySelector('.search-overlay');
    if (!overlay || !SHEET_QUERY.matches) return;
    const vv = window.visualViewport;
    const covered = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    overlay.style.bottom = `${covered}px`;
}
window.visualViewport?.addEventListener('resize', positionSheetAboveKeyboard);
window.visualViewport?.addEventListener('scroll', positionSheetAboveKeyboard);

function initializeOverlay(tempHighlight, mode = 'question') {
    const overlay = document.querySelector('.search-overlay');
    const responseContainer = document.querySelector('.search-response-container');
    const container = document.querySelector('.search-container');
    const input = overlay.querySelector('.search-input');
    const readerContent = document.getElementById('reader-content');
    
    // Reset overlay state
    overlay.classList.remove('active', 'define-mode');
    responseContainer.classList.remove('active');
    container.classList.remove('expanded');
    input.value = '';
    
    if (SHEET_QUERY.matches) {
        overlay.style.left = overlay.style.top = '';
        positionSheetAboveKeyboard();
    } else {
    // Get positions and dimensions
    const highlightRect = tempHighlight.getBoundingClientRect();
    const readerRect = readerContent.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const spaceBelow = viewportHeight - highlightRect.bottom;
    const overlayWidth = parseInt(getComputedStyle(container).width);
    
    // Position the overlay - try left first, then right, fallback to center if neither fits
    let left;
    if (highlightRect.left + overlayWidth <= readerRect.right) {
        left = highlightRect.left;
    } else if (highlightRect.right - overlayWidth >= readerRect.left) {
        left = highlightRect.right - overlayWidth;
    } else {
        left = highlightRect.left + (highlightRect.width / 2) - overlayWidth / 2;
    }
    overlay.style.left = `${left}px`;
    
    // Place below if there's enough space, otherwise place above
    if (spaceBelow >= overlay.offsetHeight + 5) {
        overlay.style.top = `${window.scrollY + highlightRect.bottom + 5}px`;
    } else {
        overlay.style.top = `${window.scrollY + highlightRect.top - overlay.offsetHeight - 5}px`;
    }
    }
    
    // Configure based on mode
    switch (mode) {
        case 'question':
            input.placeholder = 'Ask about this…';
            requestAnimationFrame(() => {
                overlay.classList.add('active');
                input.focus();
            });
            break;
        case 'explanation':
            input.placeholder = 'Ask a follow-up…';
            requestAnimationFrame(() => {
                overlay.classList.add('active', 'define-mode');
                responseContainer.classList.add('active');
            });
            break;
    }
    
    return { overlay, responseContainer, container, input };
}

function handleTextRequest(selectedString, tempHighlight, endpoint, loadingMessage) {
    const responseElement = document.querySelector('.search-response');
    const container = document.querySelector('.search-container');
    
    // Get surrounding context
    const contextNode = tempHighlight.parentNode;
    const fullText = contextNode.textContent;
    const wordIndex = fullText.indexOf(selectedString);
    const contextStart = Math.max(0, wordIndex - 100);
    const contextEnd = Math.min(fullText.length, wordIndex + selectedString.length + 100);
    const context = fullText.slice(contextStart, contextEnd);

    responseElement.className = 'thinking-animation';
    responseElement.textContent = loadingMessage;

    fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            text: selectedString,
            context: context
        })
    })
    .then(response => response.json().catch(() => ({})))
    .then(data => showAiResult(data.explanation, data.error))
    .catch(error => {
        console.error(`Error processing request:`, error);
        showAiResult(null, "Couldn't reach the library. Check your connection.");
    });
}

// Put an AI answer (or the server's plain-language error) in the box.
function showAiResult(text, error) {
    const responseElement = document.querySelector('.search-response, .thinking-animation');
    const container = document.querySelector('.search-container');
    responseElement.className = 'search-response';
    responseElement.classList.toggle('search-response--error', !text);
    responseElement.textContent = text || error || "Couldn't get an answer just now. Try again.";
    // Long answers get the wider box.
    if (text && text.length > 150) container.classList.add('expanded');
}

function handleExplainRequest(selectedString, tempHighlight) {
    handleTextRequest(selectedString, tempHighlight, appUrl('/explain'), 'Thinking');
}


// <== TIME LEFT ==>
// "14 min left in chapter · 6 h in book", from the text still ahead of you and
// your own reading speed. Speed starts at a typical 250 words a minute and
// learns from how fast you actually move through the text on this device
// (only while the page is visible and you're active; jumps don't count).
const DEFAULT_WPM = 250;
const CHARS_PER_WORD = 6;            // average English word plus its space
const SPEED_KEY = 'readerSpeed';
const SPEED_SAMPLE_MS = 20000;
const _chapterChars = {};

function chapterChars(index) {
    if (_chapterChars[index] != null) return _chapterChars[index];
    const chapter = allChapters[index];
    if (chapter) {
        const doc = new DOMParser().parseFromString(chapter.content, 'text/html');
        return (_chapterChars[index] = (doc.body.textContent || '').replace(/\s+/g, ' ').trim().length);
    }
    // Not streamed in yet: estimate from its file size, scaled by how much of
    // the loaded chapters' bytes turned out to be text — once there's enough
    // loaded to judge (a cover page alone is nearly all markup).
    const sizes = (currentBook && currentBook.chapter_sizes) || [];
    let text = 0, bytes = 0;
    Object.keys(_chapterChars).forEach((i) => { text += _chapterChars[i]; bytes += sizes[i] || 0; });
    const ratio = bytes >= 40000 ? text / bytes : 0.6;
    return Math.round((sizes[index] || 0) * ratio);
}

function positionInChapter() {
    if (isPaginated()) return totalPages > 1 ? currentPageIndex / (totalPages - 1) : 0;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    return max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
}

function readSpeedStore() {
    try { return JSON.parse(localStorage.getItem(SPEED_KEY)) || null; } catch { return null; }
}

function readingSpeed() {
    const s = readSpeedStore();
    if (!s || !s.minutes) return DEFAULT_WPM;
    // Trust what we've learned in proportion to how much we've seen (5 min = fully).
    const w = Math.min(1, s.minutes / 5);
    return DEFAULT_WPM * (1 - w) + s.wpm * w;
}

function timeLeft() {
    if (!currentBook || !allChapters[currentChapterNum]) return null;
    const wpm = readingSpeed();
    const here = chapterChars(currentChapterNum) * (1 - positionInChapter());
    // A "chapter" runs to the next entry in the contents: some books split one
    // chapter across several files.
    const end = chapterEnd(currentChapterNum);
    let restOfChapter = 0, ahead = 0;
    for (let i = currentChapterNum + 1; i < currentBook.spine_length; i++) {
        const c = chapterChars(i);
        if (i < end) restOfChapter += c;
        ahead += c;
    }
    const minutes = (chars) => chars / CHARS_PER_WORD / wpm;
    return {chapter: minutes(here + restOfChapter), book: minutes(here + ahead)};
}

// The section that starts the contents chapter `index` belongs to.
function chapterStart(index) {
    const starts = Object.keys(tocTitles).map(Number).filter((i) => i <= index);
    return starts.length ? Math.max(...starts) : index;
}

// The first section after `index` that starts a new chapter in the contents
// (or the next section, for books whose contents don't cover their files).
function chapterEnd(index) {
    const starts = Object.keys(tocTitles).map(Number);
    if (!starts.length) return index + 1;
    const next = starts.filter((i) => i > index).sort((a, b) => a - b)[0];
    return next === undefined ? currentBook.spine_length : next;
}

// A link's target file, however the book wrote the path ("../Text/x.xhtml",
// "x.xhtml#id"): chapters are keyed by file name.
function chapterForHref(href) {
    if (href == null) return undefined;
    if (href in hrefChapterMapping) return hrefChapterMapping[href];
    const name = decodeURIComponent(String(href).split('#')[0].split('/').pop());
    return hrefChapterMapping[name];
}

function formatMinutes(m) {
    if (m < 1) return 'under 1 min';
    if (m < 60) return `${Math.round(m)} min`;
    const h = Math.floor(m / 60), rest = Math.round((m % 60) / 5) * 5;
    if (h >= 10 || rest === 0 || rest === 60) return `${rest === 60 ? h + 1 : h} h`;
    return `${h} h ${rest} min`;
}

let _speedBaseline = null;
let _lastActivity = Date.now();
function resetSpeedBaseline() { _speedBaseline = null; }
['scroll', 'keydown', 'touchstart', 'wheel'].forEach((ev) =>
    window.addEventListener(ev, () => { _lastActivity = Date.now(); }, {passive: true}));
document.addEventListener('visibilitychange', resetSpeedBaseline);

setInterval(() => {
    if (!currentBook || !allChapters[currentChapterNum]) return;
    const now = Date.now();
    const here = {chapter: currentChapterNum, pos: positionInChapter(), t: now};
    const b = _speedBaseline;
    _speedBaseline = here;
    // Only count stretches where you were actually reading on this page.
    if (!b || document.hidden || now - _lastActivity > 90000) return;
    let chars;
    if (here.chapter === b.chapter) chars = (here.pos - b.pos) * chapterChars(b.chapter);
    else if (here.chapter === b.chapter + 1) chars = (1 - b.pos) * chapterChars(b.chapter) + here.pos * chapterChars(here.chapter);
    else return;
    const minutes = (now - b.t) / 60000;
    const wpm = chars / CHARS_PER_WORD / minutes;
    if (!(chars > 0) || wpm < 60 || wpm > 1200) return;   // skimming, jumping or idle
    const s = readSpeedStore() || {wpm: DEFAULT_WPM, minutes: 0};
    // A running average weighted by time spent, so long sessions settle it.
    const weight = Math.min(minutes / (s.minutes + minutes), 0.25);
    s.wpm = s.wpm * (1 - weight) + wpm * weight;
    s.minutes += minutes;
    try { localStorage.setItem(SPEED_KEY, JSON.stringify(s)); } catch { /* storage blocked */ }
    updateChapterNumberLabel();
}, SPEED_SAMPLE_MS);


// <== NOTES AND JUMPS ==>
// A footnote opens in a small pop-up beside its marker, so you never leave
// your place. Any other jump inside the book (a cross-reference, an index
// entry) shows "↩ Back to where you were".
function isNoteLink(link, targetId) {
    const label = link.textContent.trim();
    if (label.length > 4) return false;
    const sig = [link.className, link.id, targetId, link.getAttribute('epub:type'), link.getAttribute('role')]
        .join(' ').toLowerCase();
    return /note|fn|ftn|noteref/.test(sig) || !!link.closest('sup');
}

function findInChapter(index, id) {
    if (!id) return null;
    if (index === currentChapterNum) return document.getElementById(id);
    const chapter = allChapters[index];
    if (!chapter) return null;
    return new DOMParser().parseFromString(chapter.content, 'text/html').getElementById(id);
}

document.addEventListener('click', (e) => {
    const link = e.target.closest('#chapter-content a');
    if (!link) return;
    const chapterHref = link.getAttribute('chapter-link');
    const raw = link.getAttribute('href') || '';
    if (chapterHref == null && !raw.startsWith('#')) return;   // an outside link
    e.preventDefault();
    e.stopPropagation();
    const index = chapterHref != null ? chapterForHref(chapterHref) : currentChapterNum;
    const id = chapterHref != null ? link.getAttribute('section-link') : raw.slice(1);
    if (index === undefined) return;
    const target = findInChapter(index, id);
    if (target && isNoteLink(link, id)) showNote(link, target, index, id);
    else jumpWithBack(index, id);
}, true);

// Where you are, as the paragraph at the top of the screen (plus how far into
// it) rather than a fraction of the page: the page grows as images load, so a
// fraction drifts; a paragraph doesn't.
function readingBlocks() {
    // Innermost blocks only: a wrapper <div> around the whole chapter would
    // always be "the block at the top".
    return Array.from(document.querySelectorAll('#chapter-content :is(p, div):not(:has(p, div))'));
}
function currentPlace() {
    const place = {chapter: currentChapterNum, pos: currentPositionFraction(), block: -1, offset: 0};
    if (isPaginated()) return place;
    const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
    const blocks = readingBlocks();
    const i = blocks.findIndex((b) => b.getBoundingClientRect().bottom > topBar + 4);
    if (i >= 0) {
        place.block = i;
        place.offset = blocks[i].getBoundingClientRect().top - topBar;
    }
    return place;
}
function restorePlace(place) {
    if (isPaginated() || place.block < 0) {
        if (isPaginated()) relayoutPreservingPosition(place.pos);
        else jumpScroll(place.pos * document.documentElement.scrollHeight);
        return;
    }
    const block = readingBlocks()[place.block];
    if (!block) return;
    const align = () => {
        const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
        jumpScroll(window.scrollY + block.getBoundingClientRect().top - topBar - place.offset);
    };
    align();
    // Images above it may still be loading and pushing it down: keep it pinned
    // while the page settles, unless you start scrolling yourself.
    const chapterEl = document.getElementById('chapter-content');
    const ro = new ResizeObserver(align);
    ro.observe(chapterEl);
    const stop = () => {
        ro.disconnect();
        ['wheel', 'touchstart', 'keydown'].forEach((ev) => window.removeEventListener(ev, stop));
    };
    ['wheel', 'touchstart', 'keydown'].forEach((ev) => window.addEventListener(ev, stop, {passive: true}));
    setTimeout(stop, 2000);
}

function jumpWithBack(index, id) {
    const from = currentPlace();
    closeNote();
    const target = index === currentChapterNum && !isPaginated() && id ? document.getElementById(id) : null;
    if (target) {
        // Same chapter: just scroll. Re-rendering would reset the images above
        // your old place, and "Back" would then land somewhere else.
        resetSpeedBaseline();
        const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
        jumpScroll(window.scrollY + target.getBoundingClientRect().top - topBar - currentFontSize * 2);
        saveBookmark();
    } else {
        jumpToChapter(index, id);
    }
    showBackPill(from);
}

function showBackPill(from) {
    let pill = document.getElementById('back-pill');
    if (!pill) {
        pill = document.createElement('div');
        pill.id = 'back-pill';
        pill.className = 'back-pill';
        pill.innerHTML = '<button type="button" class="back-pill__go">↩ Back to where you were</button>'
            + '<button type="button" class="back-pill__close" aria-label="Dismiss">' + icon('x') + '</button>';
        document.body.appendChild(pill);
        pill.querySelector('.back-pill__close').addEventListener('click', () => { pill.hidden = true; });
    }
    pill.hidden = false;
    pill.querySelector('.back-pill__go').onclick = () => {
        pill.hidden = true;
        resetSpeedBaseline();
        // Same chapter: just scroll back (no re-render, so nothing moves).
        if (from.chapter !== currentChapterNum) jumpToChapter(from.chapter);
        requestAnimationFrame(() => requestAnimationFrame(() => {
            restorePlace(from);
            updateProgressBar();
            updateChapterNumberLabel();
            saveBookmark();
        }));
    };
}

let _noteEl = null;
function closeNote() {
    if (_noteEl) { _noteEl.remove(); _noteEl = null; }
}

function showNote(link, target, index, id) {
    closeNote();
    // The note's text lives in the block around its anchor.
    const block = target.closest('p, li, aside, div, section') || target;
    const body = block.cloneNode(true);
    body.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
    // Drop the note's own number/back-link at the start; neutralise other links.
    body.querySelectorAll('a').forEach((a, i) => {
        if (i === 0 && a.textContent.trim().length <= 4 && body.textContent.trim().startsWith(a.textContent.trim())) a.remove();
        else a.replaceWith(...a.childNodes);
    });
    // …and the punctuation that followed it ("1. The suit…" → "The suit…").
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent.trim()) continue;
        n.textContent = n.textContent.replace(/^[\s.:)\]]+/, '');
        break;
    }
    const note = document.createElement('div');
    note.className = 'note-popover';
    note.setAttribute('role', 'dialog');
    note.setAttribute('aria-label', `Note ${link.textContent.trim()}`);
    note.innerHTML = `<div class="note-popover__head"><span>Note ${link.textContent.trim()}</span>`
        + '<button type="button" class="note-popover__close" aria-label="Close">' + icon('x') + '</button></div>'
        + '<div class="note-popover__body"></div>'
        + '<button type="button" class="note-popover__open arrow-after">Open in the notes</button>';
    note.querySelector('.note-popover__body').append(...body.childNodes);
    document.body.appendChild(note);
    note.querySelector('.note-popover__close').addEventListener('click', closeNote);
    note.querySelector('.note-popover__open').addEventListener('click', () => jumpWithBack(index, id));

    // Beside the marker: below it if there's room, else above; kept on screen.
    const r = link.getBoundingClientRect();
    const w = Math.min(420, window.innerWidth - 24);
    note.style.width = `${w}px`;
    const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    const h = note.offsetHeight;
    const below = r.bottom + 10 + h < window.innerHeight;
    note.style.left = `${left + window.scrollX}px`;
    note.style.top = `${(below ? r.bottom + 10 : Math.max(12, r.top - 10 - h)) + window.scrollY}px`;
    _noteEl = note;
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeNote(); });
document.addEventListener('pointerdown', (e) => {
    if (_noteEl && !_noteEl.contains(e.target) && !e.target.closest('#chapter-content a')) closeNote();
});


// <== END OF A CHAPTER (scroll mode) ==>
// With no bottom bar, a chapter ends with a quiet link on to the next one.
// (Paginated mode turns into the next chapter with the next page.)
function addChapterEnd(root) {
    if (!currentBook || currentChapterNum >= currentBook.spine_length - 1) return;
    const next = currentChapterNum + 1;
    const title = tocTitles[next] || (allChapters[next] && allChapters[next].title) || 'Next section';
    const nav = document.createElement('nav');
    nav.className = 'chapter-end';
    nav.setAttribute('aria-label', 'Next chapter');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.innerHTML = '<span class="chapter-end__label">Next</span><span class="chapter-end__title arrow-after"></span>';
    btn.querySelector('.chapter-end__title').textContent = title;
    btn.addEventListener('click', () => nextChapter());
    nav.append(btn);
    root.append(nav);
}


// The running head and foot line up with the edges of the text, wherever the
// column or spread sits.
function alignRunningLines() {
    const content = document.getElementById('chapter-content');
    if (!content) return;
    const r = content.getBoundingClientRect();
    if (r.width <= 0) return;
    const root = document.documentElement.style;
    root.setProperty('--text-left', `${Math.max(16, Math.round(r.left))}px`);
    root.setProperty('--text-right', `${Math.max(16, Math.round(window.innerWidth - r.right))}px`);
}
window.addEventListener('resize', alignRunningLines);


// <== READING SETTINGS (the Aa panel) ==>
// Size, line spacing, width, theme and layout, remembered per device. The
// <head> script applies them before the first paint; this keeps them in sync.
const LEADING = {tight: '1.5', normal: '1.7', loose: '1.9'};
const FACES = {serif: 'var(--font-reading-serif)', classic: 'var(--font-reading-classic)', sans: 'var(--font-sans)'};
const MEASURE = {narrow: '60ch', normal: '70ch', wide: '80ch'};
const THEMES = ['day', 'sepia', 'night', 'black'];

function readerSetting(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}
function storeSetting(key, value) {
    try { localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

// The theme follows the app's day/night switch (the library shares it):
// Day and Sepia are day themes, Night and Black are night ones.
function currentTheme() {
    const dark = document.documentElement.classList.contains('dark-mode');
    const t = readerSetting('readerTheme', dark ? 'night' : 'day');
    if (dark && (t === 'day' || t === 'sepia')) return 'night';
    if (!dark && (t === 'night' || t === 'black')) return 'day';
    return t;
}
function setTheme(theme) {
    const root = document.documentElement;
    const dark = theme === 'night' || theme === 'black';
    root.classList.toggle('dark-mode', dark);
    root.classList.toggle('theme-sepia', theme === 'sepia');
    root.classList.toggle('theme-black', theme === 'black');
    storeSetting('darkMode', dark ? 'enabled' : 'disabled');
    storeSetting('readerTheme', theme);
    syncSettingsPanel();
}
// N: day ↔ night, keeping a Sepia or Black preference within its half.
function toggleNight() {
    const t = currentTheme();
    setTheme(t === 'night' || t === 'black' ? 'day' : 'night');
}

function setFont(value) {
    storeSetting('readerFont', value);
    document.documentElement.style.setProperty('--reader-font', FACES[value] || FACES.serif);
    if (isPaginated()) relayoutPreservingPosition();
    alignRunningLines();
}

function setLeading(value) {
    storeSetting('readerLeading', value);
    document.documentElement.style.setProperty('--reader-leading', LEADING[value]);
    if (isPaginated()) relayoutPreservingPosition();
}
function setWidth(value) {
    storeSetting('readerWidth', value);
    document.documentElement.style.setProperty('--reader-measure', MEASURE[value]);
    if (isPaginated()) relayoutPreservingPosition();
    alignRunningLines();
}

// Horizontal or vertical text, for this book. Re-renders the chapter (numbers
// stand upright only in vertical text) and keeps your place in the text.
function setDirection(value) {
    const offset = firstVisibleTextOffset();
    const fraction = currentPositionFraction();
    storeSetting(VERTICAL_KEY, value);
    const content = document.getElementById('chapter-content');
    content.scrollLeft = 0;
    content.style.clipPath = '';
    jumpScroll(0);
    displayChapter();
    updateReadingModeButton();
    requestAnimationFrame(() => {
        const rect = offset >= 0 ? rectAtTextOffset(offset) : null;
        if (isPaginated()) {
            if (rect) {
                currentPageIndex = Math.min(pageOfRect(rect), totalPages - 1);
                applyPageTransform(false);
            } else {
                relayoutPreservingPosition(fraction);
            }
        } else if (rect) {
            const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
            jumpScroll(window.scrollY + rect.top - topBar - currentFontSize * 2);
        } else {
            jumpScroll(fraction * document.documentElement.scrollHeight);
        }
        updateProgressBar();
        updateChapterNumberLabel();
        saveBookmark();
    });
}

function syncSettingsPanel() {
    const panel = document.getElementById('reader-settings');
    if (!panel) return;
    const size = document.getElementById('rs-size');
    if (size) size.textContent = currentFontSize;
    const values = {
        font: readerSetting('readerFont', 'serif'),
        leading: readerSetting('readerLeading', 'normal'),
        width: readerSetting('readerWidth', 'normal'),
        theme: currentTheme(),
        layout: isPaginated() ? 'paginate' : 'scroll',
        direction: isVertical() ? 'vertical' : 'horizontal',
    };
    // Text direction is offered for Chinese and Japanese books; vertical text
    // reads in pages, so Scroll is greyed out while it's on.
    const direction = document.getElementById('rs-direction');
    if (direction) direction.hidden = !verticalAvailable();
    const scroll = panel.querySelector('[data-setting="layout"] [data-value="scroll"]');
    if (scroll) {
        scroll.disabled = isVertical();
        scroll.title = isVertical() ? 'Vertical text reads in pages' : '';
    }
    const note = document.getElementById('rs-layout-note');
    if (note) note.hidden = !isVertical();
    panel.querySelectorAll('.rs-seg').forEach((seg) => {
        if (!(seg.dataset.setting in values)) return;   // read aloud keeps its own (read_aloud.js)
        seg.querySelectorAll('button').forEach((b) =>
            b.setAttribute('aria-pressed', b.dataset.value === values[seg.dataset.setting] ? 'true' : 'false'));
    });
}

function openSettings(open) {
    const panel = document.getElementById('reader-settings');
    const btn = document.getElementById('settings-toggle');
    if (!panel || !btn) return;
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.querySelector('.top-controls').classList.toggle('pinned', open);
    if (open) document.documentElement.classList.add('bar-visible');
    if (open) syncSettingsPanel();
}

document.addEventListener('DOMContentLoaded', () => {
    const panel = document.getElementById('reader-settings');
    const btn = document.getElementById('settings-toggle');
    if (!panel || !btn) return;
    btn.addEventListener('click', (e) => { e.stopPropagation(); openSettings(panel.hidden); });
    panel.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.size) { adjustFontSize(Number(b.dataset.size)); return; }
        const setting = b.closest('.rs-seg')?.dataset.setting;
        const v = b.dataset.value;
        if (setting === 'font') setFont(v);
        else if (setting === 'leading') setLeading(v);
        else if (setting === 'width') setWidth(v);
        else if (setting === 'theme') setTheme(v);
        else if (setting === 'layout' && v !== (isPaginated() ? 'paginate' : 'scroll')) toggleReadingMode();
        else if (setting === 'direction' && v !== (isVertical() ? 'vertical' : 'horizontal')) setDirection(v);
        syncSettingsPanel();
    });
    document.addEventListener('pointerdown', (e) => {
        if (!panel.hidden && !panel.contains(e.target) && !btn.contains(e.target)) openSettings(false);
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) openSettings(false); });
    syncSettingsPanel();
});


// <== SMALL COMFORTS ==>
// On opening a book, softly mark the paragraph you stopped at so your eyes
// find it; the mark fades on its own.
function markYourPlace() {
    let block = null;
    if (isPaginated()) block = firstVisibleBlock();
    else {
        const place = currentPlace();
        block = place.block >= 0 ? readingBlocks()[place.block] : null;
    }
    if (!block) return;
    block.classList.add('your-place');
    setTimeout(() => block.classList.remove('your-place'), 2600);
}

// Keep the screen awake while a book is open and visible (phones would
// otherwise dim mid-page). The browser drops the lock when the tab hides.
let _wakeLock = null;
async function keepAwake() {
    if (!('wakeLock' in navigator) || document.hidden || _wakeLock) return;
    try {
        _wakeLock = await navigator.wakeLock.request('screen');
        _wakeLock.addEventListener('release', () => { _wakeLock = null; });
    } catch { /* not allowed (battery saver, no gesture yet): fine */ }
}
document.addEventListener('visibilitychange', keepAwake);
['click', 'keydown', 'touchend'].forEach((ev) => document.addEventListener(ev, keepAwake, {passive: true}));
keepAwake();
