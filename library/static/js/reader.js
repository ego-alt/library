let currentBook = null;
let currentChapter = null;
const filename = window.location.pathname.split('/').pop();

let allChapters = [];
let currentChapterNum = 0;
let currentPagePosition = 0;
let currentFontSize = parseInt(localStorage.getItem('readerFontSize')) || 16;
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
const PAGE_GAP = 40;
const SPREAD_WIDTH_THRESHOLD = 1000; // px — show 2-up when viewport is at least this wide
const READER_MAX_W_SINGLE = 820;
const READER_MAX_W_SPREAD = 1280;

function isPaginated() { return readingMode === 'paginate'; }

function applyReadingModeClass() {
    document.documentElement.classList.toggle('paginated', isPaginated());
}

function updateReadingModeButton() {
    const btn = document.getElementById('reading-mode-toggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    if (icon) icon.className = isPaginated() ? 'fas fa-scroll' : 'fas fa-book-open';
    btn.title = isPaginated() ? 'Switch to scroll view' : 'Switch to paginated view';
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

    spreadCount = computeSpreadCount();
    const maxW = spreadCount === 2 ? READER_MAX_W_SPREAD : READER_MAX_W_SINGLE;
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
    const totalCols = Math.max(1, Math.round(content.scrollWidth / step));
    totalPages = Math.max(1, Math.ceil(totalCols / spreadCount));
    currentPageIndex = Math.max(0, Math.min(currentPageIndex, totalPages - 1));
    applyPageTransform(false);
}

const PAGE_FLIP_MS = 140;
let _pageFlipRaf = null;

// Custom rAF animation: the browser's smooth scroll is ~300ms with no knob,
// and that feels slow for a page turn. 140ms ease-out lands snappy without
// the harshness of instant scroll.
function applyPageTransform(animate = true) {
    const content = document.getElementById('chapter-content');
    if (!content) return;
    const targetLeft = currentPageIndex * spreadStep();

    if (_pageFlipRaf) {
        cancelAnimationFrame(_pageFlipRaf);
        _pageFlipRaf = null;
    }
    if (!animate) {
        content.scrollLeft = targetLeft;
        return;
    }

    const startLeft = content.scrollLeft;
    const delta = targetLeft - startLeft;
    if (Math.abs(delta) < 1) {
        content.scrollLeft = targetLeft;
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
        }
    }
    _pageFlipRaf = requestAnimationFrame(step);
}

function pageOfElement(el) {
    if (!el) return 0;
    const content = document.getElementById('chapter-content');
    // Measure via bounding rect offset; offsetLeft would be wrong if any
    // intermediate ancestor is positioned.
    const contentRect = content.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    // Add current scrollLeft because rects are viewport-relative.
    const x = (elRect.left - contentRect.left) + content.scrollLeft;
    const step = spreadStep();
    return step > 0 ? Math.max(0, Math.floor(x / step)) : 0;
}

function updateChapterNumberLabel() {
    if (!currentBook) return;
    const el = document.getElementById('chapter-number');
    let text = `Section ${currentChapterNum + 1} of ${currentBook.spine_length}`;
    if (isPaginated() && totalPages > 1) {
        text += ` · ${currentPageIndex + 1}/${totalPages}`;
    }
    el.textContent = text;
}

function nextPage() {
    if (!currentBook) return;
    if (currentPageIndex < totalPages - 1) {
        currentPageIndex++;
        applyPageTransform(true);
        updateProgressBar();
        updateChapterNumberLabel();
        saveBookmark();
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
    if (!currentBook) return;
    // Capture position before switching so we can land on roughly the same
    // content in the new mode.
    const fraction = currentPositionFraction();
    readingMode = isPaginated() ? 'scroll' : 'paginate';
    localStorage.setItem('readingMode', readingMode);
    applyReadingModeClass();
    updateReadingModeButton();

    if (isPaginated()) {
        // Clear stray scroll position so the page columns line up cleanly.
        window.scrollTo(0, 0);
        requestAnimationFrame(() => {
            layoutPaginatedChapter();
            currentPageIndex = Math.round(fraction * Math.max(0, totalPages - 1));
            applyPageTransform(false);
            updateProgressBar();
            updateChapterNumberLabel();
        });
    } else {
        // Reset column scroll so going back into paginate mode later isn't
        // sticky if user had it half-scrolled.
        const content = document.getElementById('chapter-content');
        if (content) content.scrollLeft = 0;
        requestAnimationFrame(() => {
            const target = fraction * document.documentElement.scrollHeight;
            window.scrollTo({top: target, behavior: 'instant'});
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
document.documentElement.style.setProperty('--highlight-color', 'rgba(225, 204, 171)'); // Light mode
document.documentElement.style.setProperty('--highlight-color-dark', 'rgba(58, 109, 154, 0.6)'); // Dark mode

// Initialize overlay and event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Add overlay HTML
    const overlay = document.createElement('div');
    overlay.className = 'search-overlay';
    overlay.innerHTML = `
        <div class="search-container">
            <div class="search-input-container">
                <input type="text" class="search-input" placeholder="Ask a quick question...">
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
    selectionMenu.innerHTML = `
        <button class="ask-button" title="Ask a question">
            <i class="fas fa-question"></i>
        </button>
        <button class="define-button" title="Define word">
            <i class="fas fa-book"></i>
        </button>
        <button class="translate-button" title="Translate text">
            <i class="fas fa-language"></i>
        </button>
    `;
    document.body.appendChild(selectionMenu);

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
                responseElement.textContent = 'Thinking.'
                
                // Create thinking animation
                let dots = 0;
                responseElement.className = 'thinking-animation';
                const thinkingAnimation = setInterval(() => {
                    dots = (dots + 1) % 11;
                    responseElement.textContent = 'Thinking' + '.'.repeat(dots);
                }, 200);
                
                try {
                    const response = await fetch(appUrl('/ask_question'), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            context: highlightedText,
                            question: userInput
                        })
                    });

                    const data = await response.json();

                    // Clear thinking animation
                    clearInterval(thinkingAnimation);
                    responseElement.className = 'search-response';
                    responseElement.textContent = data.answer;
                    
                    // Only expand if answer is over 150 characters
                    if (data.answer.length > 150) {
                        container.classList.add('expanded');
                    }
                } catch (error) {
                    console.error('Error getting answer:', error);
                    // Clear thinking animation and show error
                    clearInterval(thinkingAnimation);
                    responseElement.className = 'search-response';
                    responseElement.textContent = 'Sorry, an error occurred while getting the answer.';
                }
            }
        }
    });

    // Handle keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'd' || e.key === 'l')) {
            e.preventDefault();
            
            const selection = window.getSelection();
            const selectedString = selection.toString().trim(); 
            if (!selection.rangeCount || !selectedString) return;
            
            // Store the selected range and create highlight
            selectedRange = selection.getRangeAt(0).cloneRange();
            const tempHighlight = wrapRangeInHighlight(selectedRange);
            if (!tempHighlight) return;

            if (e.key === 'k') {
                initializeOverlay(tempHighlight, 'question');
            } else if (e.key === 'd') {
                initializeOverlay(tempHighlight, 'definition');
                handleDefinitionRequest(selectedString, tempHighlight);
            } else if (e.key === 'l') {
                initializeOverlay(tempHighlight, 'translation');
                handleTranslationRequest(selectedString, tempHighlight);
            }
        }
    });

    // Toggle menu visibility
    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            document.getElementById('toc-menu').classList.toggle('visible');
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

    // Handle text selection on mobile/touch devices
    document.addEventListener('selectionchange', () => {
        const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
        if (!isTouchDevice) return;

        const selection = window.getSelection();
        const selectionMenu = document.querySelector('.selection-menu');
        const selectedString = selection.toString().trim();

        if (!selection.rangeCount || !selectedString) {
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
        document.querySelector('.define-button').onclick = () => handleSelectionAction('definition');
        document.querySelector('.translate-button').onclick = () => handleSelectionAction('translation');
    });

    // Handle selection menu actions
    function handleSelectionAction(action) {
        const selection = window.getSelection();
        const selectedString = selection.toString().trim();
        if (!selection.rangeCount || !selectedString) return;

        // Create highlight
        const tempHighlight = wrapRangeInHighlight(selectedRange);
        if (!tempHighlight) return;

        // Initialize overlay and handle action
        initializeOverlay(tempHighlight, action);
        if (action === 'definition') {
            handleDefinitionRequest(selectedString, tempHighlight);
        } else if (action === 'translation') {
            handleTranslationRequest(selectedString, tempHighlight);
        }

        // Hide the selection menu
        document.querySelector('.selection-menu').classList.remove('active');
    }
});

// Load book on page load
window.addEventListener('DOMContentLoaded', () => { 
    document.getElementById('loading-spinner').style.display = 'block';
    // Show controls immediately on load
    document.querySelector('.top-controls').classList.add('visible');
    
    fetch(appUrl(`/load_book/${filename}`))
        .then(response => {
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
                            currentChapterNum = currentBook.start_chapter;
                            currentPagePosition = currentBook.chapter_pos;
                            displayBookMetadata();
                            break;
                        case 'chapter':
                            currentChapter = data;
                            chapterNum = currentChapter.index;
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
                                        layoutPaginatedChapter();
                                        currentPageIndex = Math.round(
                                            currentPagePosition * Math.max(0, totalPages - 1)
                                        );
                                        applyPageTransform(false);
                                        updateProgressBar();
                                        updateChapterNumberLabel();
                                    } else {
                                        window.scrollTo({
                                            top: currentPagePosition * document.documentElement.scrollHeight,
                                            behavior: 'instant'
                                        });
                                    }
                                });
                            }
                    }    
                }
            }
            function readStream() {
                reader.read().then(({done, value}) => {
                    if (done) {
                        if (buffer) {
                            processChunk('');
                        }
                        return;
                    }
                    processChunk(decoder.decode(value, {stream: true}));
                    readStream();
                }).catch(error => {
                    console.error('Error reading stream:', error);
                    document.getElementById('loading-spinner').style.display = 'none';
                    document.getElementById('chapter-content').innerHTML = 
                        '<div class="alert alert-danger">Error loading book. Please try again.</div>';
                });
            }
            readStream();
        })
});

function displayBookMetadata() {
    document.getElementById('book-title').textContent = currentBook.title;
    document.getElementById('book-author').textContent = `by ${currentBook.author}`;

    const tocContent = document.getElementById('toc-content');
    tocContent.replaceChildren(buildTocList(currentBook.toc || []));
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

function saveBookmark() {
    if (!lastSaveTimeout) {
        lastSaveTimeout = setTimeout(() => {
            let position;
            if (isPaginated()) {
                position = totalPages > 1 ? currentPageIndex / (totalPages - 1) : 0;
            } else {
                position = window.scrollY / document.documentElement.scrollHeight;
            }

            fetch(appUrl(`/bookmark/${filename}`), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    chapter_index: currentChapterNum,
                    position: position
                })
            }).catch(error => console.error('Error saving bookmark:', error));

            lastSaveTimeout = null;
        }, 1000); // Debounce save for 1 second
    }
}

function displayChapter() {
    const content = allChapters[currentChapterNum].content;
    document.getElementById('chapter-content').innerHTML = content;

    if (isPaginated()) {
        currentPageIndex = 0;
        layoutPaginatedChapter();
    }
    updateChapterNumberLabel();

    // Initialize progress bar position
    updateProgressBar();

    // Show controls on chapter load
    const controls = document.querySelector('.top-controls');
    controls.classList.add('visible');
    showBottomControls();

    // Add scroll listener
    let lastScrollY = window.scrollY;
    const scrollHandler = () => {
        const currentScrollY = window.scrollY;
        if (currentScrollY > lastScrollY && currentScrollY > 100) {
            // Scrolling down and past 100px - hide controls
            controls.classList.remove('visible');
        } else if (currentScrollY < 50) {
            // Near the top - show controls
            controls.classList.add('visible');
        }
        lastScrollY = currentScrollY;
    };

    // Remove previous scroll listener if it exists
    window.removeEventListener('scroll', scrollHandler);
    // Add new scroll listener
    window.addEventListener('scroll', scrollHandler);
}

function nextChapter() {
    if (currentChapterNum < currentBook.spine_length - 1) {
        currentChapterNum++;
        displayChapter();
        if (isPaginated()) {
            currentPageIndex = 0;
            applyPageTransform(false);
        } else {
            window.scrollTo({top: 0, behavior: 'instant'});
        }
        updateProgressBar();
        updateChapterNumberLabel();
        highlightActiveTocItem();
        saveBookmark();
    }

    if (currentChapterNum === currentBook.spine_length - 1) {
        fetch(appUrl(`/tag_finished/${filename}`), {
            method: 'POST'
        }).catch(error => console.error('Error adding tag:', error));
    }
}

function prevChapter() {
    if (currentChapterNum > 0) {
        currentChapterNum--;
        displayChapter();
        if (isPaginated()) {
            // Land on the last page so "prev" from page 1 of chapter N lands
            // at the end of chapter N-1, mirroring the scroll-mode behaviour
            // of jumping to the bottom of the previous chapter.
            currentPageIndex = Math.max(0, totalPages - 1);
            applyPageTransform(false);
        } else {
            window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'});
        }
        updateProgressBar();
        updateChapterNumberLabel();
        highlightActiveTocItem();
        saveBookmark();
    }
}

function jumpToChapter(index, sectionId) {
    if (index < 0 || !allChapters[index]) return;
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
                window.scrollTo({
                    top: window.pageYOffset + target.getBoundingClientRect().top - offset,
                    behavior: 'instant',
                });
            } else {
                window.scrollTo({top: 0, behavior: 'instant'});
            }
        });
    } else {
        window.scrollTo({top: 0, behavior: 'instant'});
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
    if (isPaginated()) {
        // Capture the position fraction so we land near the same content
        // after the relayout, then recompute totalPages.
        const fraction = currentPositionFraction();
        layoutPaginatedChapter();
        currentPageIndex = Math.round(fraction * Math.max(0, totalPages - 1));
        applyPageTransform(false);
        updateProgressBar();
        updateChapterNumberLabel();
    }
}

// Update scroll event listener to handle both functions
window.addEventListener('scroll', () => {
    updateProgressBar();
    saveBookmark();
    showBottomControls();
});


// <== AUTO-HIDE BOTTOM CONTROLS ==>
// Bottom bar fades out after a few seconds of mouse/touch inactivity, so it
// doesn't sit on top of the last line you're reading. Any mouse movement,
// touch, hover near the bottom edge, or chapter change brings it back.
const CONTROLS_AUTOHIDE_MS = 2500;
let _controlsAutoHideTimer = null;

function showBottomControls() {
    const c = document.querySelector('.controls');
    if (!c) return;
    c.classList.remove('controls--hidden');
    scheduleControlsAutoHide();
}

function scheduleControlsAutoHide() {
    if (_controlsAutoHideTimer) clearTimeout(_controlsAutoHideTimer);
    _controlsAutoHideTimer = setTimeout(() => {
        const c = document.querySelector('.controls');
        if (c) c.classList.add('controls--hidden');
    }, CONTROLS_AUTOHIDE_MS);
}

// Reveal on mouse / touch activity. Keydown is *not* a trigger because in
// paginated mode every page turn would flash the bar.
document.addEventListener('mousemove', showBottomControls, {passive: true});
document.addEventListener('touchstart', showBottomControls, {passive: true});
// Hovering near the bottom edge of the viewport reveals the bar even when
// the user isn't moving the mouse — CSS sibling selector can't reach the
// controls from here, so handle it in JS.
document.querySelector('.bottom-trigger')?.addEventListener('mouseenter', showBottomControls);


// <== PAGINATED MODE: input + lifecycle ==>
// Plain arrows = page nav (paginated only). Shift+arrows = section jump
// (both modes). Avoids stealing keys from inputs or from the existing
// Cmd/Ctrl+K/D/L selection shortcuts.
document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, textarea')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.shiftKey) {
        if (e.key === 'ArrowRight') {
            e.preventDefault();
            nextChapter();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            prevChapter();
        }
        return;
    }

    if (!isPaginated()) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {
        e.preventDefault();
        nextPage();
    } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault();
        prevPage();
    }
});

// Click left third of the reader to go back a page, right third forward.
// Middle third is a no-op so text selection still works freely.
document.addEventListener('click', (e) => {
    if (!isPaginated()) return;
    // Don't trigger when clicking interactive chrome or the user has text
    // selected (probably trying to use the selection menu).
    if (e.target.closest(
        'button, a, input, textarea, .toc-menu, .top-controls, .controls, ' +
        '.selection-menu, .search-overlay, .temp-highlight'
    )) return;
    if (window.getSelection().toString().trim()) return;

    const w = window.innerWidth;
    if (e.clientX < w * 0.35) {
        prevPage();
    } else if (e.clientX > w * 0.65) {
        nextPage();
    }
});

// <== SCROLL MODE: horizontal swipe → section nav ==>
// Paginated mode has the tap-zones above; scroll mode has no natural touch
// gesture for moving between sections, so map a horizontal swipe to prev/next.
// Vertical-dominant gestures fall through to normal scrolling, and an active
// text selection suppresses nav so the selection menu stays usable.
const SWIPE_MIN_PX = 70;        // ignore short drags
let _swipeStartX = null, _swipeStartY = null;
document.addEventListener('touchstart', (e) => {
    if (isPaginated() || e.touches.length !== 1) { _swipeStartX = null; return; }
    // Ignore swipes that start on interactive chrome.
    if (e.target.closest(
        'button, a, input, textarea, .toc-menu, .top-controls, ' +
        '.controls, .selection-menu, .search-overlay'
    )) { _swipeStartX = null; return; }
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
    if (dx < 0) nextChapter(); else prevChapter();
}, {passive: true});

// Recompute pagination on resize. Debounced; preserves the user's relative
// position in the chapter across the relayout.
let _readerResizeTimer;
window.addEventListener('resize', () => {
    if (!isPaginated()) return;
    clearTimeout(_readerResizeTimer);
    _readerResizeTimer = setTimeout(() => {
        const fraction = currentPositionFraction();
        layoutPaginatedChapter();
        currentPageIndex = Math.round(fraction * Math.max(0, totalPages - 1));
        applyPageTransform(false);
        updateProgressBar();
        updateChapterNumberLabel();
    }, 150);
});

// Reflect the persisted mode in the toggle button as soon as the DOM is ready,
// before the book has streamed in.
document.addEventListener('DOMContentLoaded', () => {
    applyReadingModeClass();
    updateReadingModeButton();
});

// Resolve in-content chapter links via the same path as TOC clicks.
function handleChapterLink(element) {
    const href = element.getAttribute('chapter-link');
    const sectionId = element.getAttribute('section-link');
    const targetChapter = hrefChapterMapping[href];
    if (targetChapter === undefined) return;
    jumpToChapter(targetChapter, sectionId);
}

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
    
    // Configure based on mode
    switch (mode) {
        case 'question':
            input.placeholder = 'Ask a quick question...';
            requestAnimationFrame(() => {
                overlay.classList.add('active');
                input.focus();
            });
            break;
        case 'definition':
        case 'translation':
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
            [endpoint.includes('translate') ? 'text' : 'word']: selectedString,
            context: context
        })
    })
    .then(response => response.json())
    .then(data => {
        responseElement.className = 'search-response';
        const result = data.translation || data.definition;
        responseElement.textContent = result;
        
        // Only expand if result is over 150 characters
        if (result.length > 150) {
            container.classList.add('expanded');
        }
    })
    .catch(error => {
        console.error(`Error processing request:`, error);
        responseElement.className = 'search-response';
        responseElement.textContent = 'Sorry, an error occurred while processing your request.';
    });
}

function handleDefinitionRequest(selectedString, tempHighlight) {
    handleTextRequest(selectedString, tempHighlight, appUrl('/define_word'), 'Looking up definition...');
}

function handleTranslationRequest(selectedString, tempHighlight) {
    handleTextRequest(selectedString, tempHighlight, appUrl('/translate_text'), 'Translating...');
}