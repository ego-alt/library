// How many books are already on the page (the server renders the first batch).
let offset = window.initialBookCount || 0;
let isLoading = false;
let allImagesLoaded = false;
let currentFilters = {};
// View state — reading status: 'all' (newest first), 'unread', 'reading' or
// 'finished' (the last two by when you last read). The server picks the
// opening view (Reading when something's in progress, else All); it isn't
// remembered between visits, so the page always opens on what you're reading.
const VIEWS = ['all', 'unread', 'reading', 'finished'];
function normalizeView(v) { return v === 'mine' ? 'reading' : (VIEWS.includes(v) ? v : 'all'); }
let currentView = normalizeView(window.initialView);
// Mirror of every book currently displayed, in insertion order. Seeded from the
// server-rendered HTML and appended to by loadMoreImages, so the wall can be
// re-rendered (after a delete, or coming back from a book) without re-fetching.
const loadedBooks = [];
// Total books available for the current view+filter. Server seeds it on
// initial render; each /load_more response refreshes it via X-Total-Count.
// Used to cap the number of loading skeletons we render.
let totalBooks = (typeof window.totalBooks === 'number') ? window.totalBooks : null;

// "Title by Author", for alt text and labels. Falls back to the filename for
// payloads that predate title/author.
function bookLabel(book) {
    if (!book.title) return book.filename;
    return book.author ? `${book.title} by ${book.author}` : book.title;
}

function appendBookToLibrary(book) {
    $('#library').append(getBookTemplate(book));
}

function getBookTemplate(book) {
    const n = Math.floor((book.progress || 0) * 100);
    const lock = book.access_level && book.access_level !== 'standard'
        ? h('span', {class: 'book-lock', title: 'Private — only admins can see this', 'aria-label': 'Private'}, iconEl('lock'))
        : null;
    return coverCard({
        href: appUrl(`/read/${encodeURIComponent(book.filename)}`),
        label: `Read ${bookLabel(book)}`,
        title: book.title || '',
        meta: [book.author, n > 0 ? `${n}%` : ''],
        cover: book.cover,
        extras: [lock, h('div', {class: 'book-buttons'},
            h('button', {class: 'book-button', dataset: {action: 'show-metadata', filename: book.filename}, 'aria-label': 'Details', title: 'Details'},
                iconEl('ellipsis')))],
    });
}

function nearPageBottom(thresholdPx = 100) {
    return $(window).scrollTop() + $(window).height() >= $(document).height() - thresholdPx;
}

/** On a tall screen the first batch can fit without scrolling — no scroll
 *  event fires and /load_more never runs. Keep fetching until the document is
 *  tall enough to scroll (or everything is loaded). */
function tryLoadMoreIfPageStillShort() {
    if (isLoading || allImagesLoaded) return;
    if ($(document).height() <= $(window).height() + 100) {
        loadMoreImages();
    }
}

$(window).scroll(function() {
    if (!isLoading && !allImagesLoaded && nearPageBottom()) {
        loadMoreImages();
    }
});

// Add debounce function
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// Update loadMoreImages function to use filters
// When a search or view change reloads the grid, the old results stay up
// (dimmed) until the new ones arrive, instead of flashing an empty page.
let replaceOnLoad = false;
// Bumped on every reload; responses from an older search/view are ignored.
let loadGeneration = 0;

function loadMoreImages() {
    isLoading = true;
    const generation = loadGeneration;
    const replacing = replaceOnLoad;
    const skeletons = replacing ? [] : appendSkeletons(computeSkeletonCount());
    if (replacing) $('#library').addClass('is-refreshing');

    const queryParams = new URLSearchParams(currentFilters);
    queryParams.set('view', currentView);

    $.get(appUrl(`/load_more/${offset}?${queryParams.toString()}`), function(data, _status, jqXHR) {
        skeletons.forEach(el => el.remove());
        if (generation !== loadGeneration) return;  // superseded by a newer search
        if (replacing) {
            replaceOnLoad = false;
            loadedBooks.length = 0;
            $('#library').empty().removeClass('is-refreshing');
        }
        const reported = parseInt(jqXHR.getResponseHeader('X-Total-Count'), 10);
        if (!Number.isNaN(reported)) totalBooks = reported;

        if (data.length === 0) {
            allImagesLoaded = true;
            if (loadedBooks.length === 0) {
                renderEmptyState();
                $('#library').hide();
            }
        } else {
            $('#emptyState').hide();
            $('#library').show();
            data.forEach(function(book) {
                loadedBooks.push(book);
                appendBookToLibrary(book);
            });
        }
        offset += data.length;
        isLoading = false;
        requestAnimationFrame(tryLoadMoreIfPageStillShort);
    }).fail(function() {
        skeletons.forEach(el => el.remove());
        if (generation !== loadGeneration) return;
        $('#library').removeClass('is-refreshing');
        replaceOnLoad = false;
        isLoading = false;
        showToast("Couldn't load more books.", 'error', {label: 'Retry', onClick: loadMoreImages});
    });
}

const SKELETON_COUNT = 8;

function computeSkeletonCount() {
    // If we don't know the total yet (e.g. anonymous browse before first
    // /load_more response), assume a full page worth of cards.
    if (totalBooks == null) return SKELETON_COUNT;
    const displayed = document.querySelectorAll('#library .col-md-3:not(.book-skeleton-wrapper)').length;
    return Math.min(SKELETON_COUNT, Math.max(0, totalBooks - displayed));
}

function appendSkeletons(count) {
    const grid = document.getElementById('library');
    if (!grid || count <= 0) return [];
    grid.style.display = '';
    const created = [];
    for (let i = 0; i < count; i++) {
        const el = document.createElement('div');
        el.className = 'col-md-3 mb-3 book-skeleton-wrapper';
        el.innerHTML = '<div class="book-skeleton" aria-hidden="true"></div>';
        grid.appendChild(el);
        created.push(el);
    }
    return created;
}


// <== GLOBAL CLICK DELEGATION ==>
// Single dispatcher for data-action buttons. Replaces inline onclick handlers
// so user-supplied data (filenames, tags) never gets interpolated into HTML
// or JS strings.
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-action]');
    if (!trigger) return;
    const filename = trigger.dataset.filename;
    switch (trigger.dataset.action) {
        case 'show-metadata':  showMetadata(filename); break;
        case 'change-cover':   triggerCoverUpload(filename); break;
        case 'delete-book':    deleteBook(filename); break;
        case 'save-metadata':  saveMetadata(filename); break;
        case 'save-new-book':  saveNewBook(); break;
    }
});


const EMPTY_STATES = {
    unread: ["Nothing unread", "Every book here has been opened. Time for a new one?"],
    reading: ["Nothing on the go", "Books you start reading will appear here."],
    finished: ["Nothing finished yet", "Books you mark as finished will appear here."],
};

function renderEmptyState() {
    const $empty = $('#emptyState');
    const searching = Boolean(currentFilters.q);
    let [title, body] = ["Your shelves are empty", window.isAuthenticated
        ? "Add an EPUB to begin." : "Sign in to add books."];
    if (searching) {
        [title, body] = [`Nothing matches “${currentFilters.q}”`, "Try a different word, or clear the search."];
    } else if (EMPTY_STATES[currentView]) {
        [title, body] = EMPTY_STATES[currentView];
    }
    $empty.find('h3').text(title);
    $empty.find('p').text(body);
    $empty.find('.empty-action').prop('hidden', searching || currentView !== 'all' || !window.isAuthenticated);
    $empty.show();
}


// <== READING-STATUS VIEW (All / Unread / Reading / Finished) ==>
function setView(view) {
    currentView = normalizeView(view);
    updateViewUI();
    reloadLibrary();
}

function updateViewUI() {
    document.querySelectorAll('.status-filter [data-view]').forEach(btn => {
        btn.setAttribute('aria-checked', btn.dataset.view === currentView ? 'true' : 'false');
    });
}

document.querySelectorAll('.status-filter [data-view]').forEach(btn => {
    btn.addEventListener('click', () => {
        if (btn.dataset.view !== currentView) setView(btn.dataset.view);
    });
});

function reloadLibrary() {
    loadGeneration += 1;
    isLoading = false;
    offset = 0;
    allImagesLoaded = false;
    replaceOnLoad = loadedBooks.length > 0;
    if (!replaceOnLoad) $('#library').empty();
    $('#emptyState').hide();
    $('#library').show();
    loadMoreImages();
}

// <== COMING BACK FROM A BOOK ==>
// Leaving the library saves what was on screen (books loaded, search, scroll
// position) for this tab; returning from the reader puts it all back
// instead of starting over at the top.
const RETURN_STATE_KEY = 'libraryReturnState';
const RETURN_STATE_MAX_AGE = 30 * 60 * 1000;

window.addEventListener('pagehide', () => {
    try {
        sessionStorage.setItem(RETURN_STATE_KEY, JSON.stringify({
            t: Date.now(), books: loadedBooks, offset, allImagesLoaded, totalBooks,
            q: currentFilters.q || '', view: currentView, scrollY: window.scrollY,
        }));
    } catch { /* storage full or blocked */ }
});

function restoreReturnState() {
    let state = null;
    try {
        state = JSON.parse(sessionStorage.getItem(RETURN_STATE_KEY));
        sessionStorage.removeItem(RETURN_STATE_KEY);
    } catch { return false; }
    const fromReader = document.referrer.includes('/read/');
    if (!state || !fromReader || Date.now() - state.t > RETURN_STATE_MAX_AGE
        || !Array.isArray(state.books) || !state.books.length) return false;

    currentView = normalizeView(state.view);
    currentFilters = state.q ? {q: state.q} : {};
    $('#librarySearch').val(state.q);
    loadedBooks.length = 0;
    loadedBooks.push(...state.books);
    offset = state.offset;
    allImagesLoaded = state.allImagesLoaded;
    totalBooks = state.totalBooks;
    rerenderLibrary();
    updateViewUI();
    requestAnimationFrame(() => window.scrollTo(0, state.scrollY || 0));
    return true;
}

$(function() {
    if (restoreReturnState()) return;
    updateViewUI();

    // Mirror the server-rendered covers into loadedBooks (see above).
    seedLoadedBooksFromDOM();
    if (totalBooks === 0) {
        renderEmptyState();
        // Nothing to search or sort yet.
        if (currentView === 'all') $('.library-toolbar').prop('hidden', true);
    }
    requestAnimationFrame(tryLoadMoreIfPageStillShort);
});


// <== THE WALL'S MIRROR ==>
function seedLoadedBooksFromDOM() {
    document.querySelectorAll('#library .col-md-3').forEach((col) => {
        const link = col.querySelector('a[href*="/read/"]');
        const img = col.querySelector('img');
        if (!link) return;  // (a cover that failed to load has no img)
        const href = link.getAttribute('href') || '';
        const readMarker = '/read/';
        const readIdx = href.indexOf(readMarker);
        if (readIdx === -1) return;
        loadedBooks.push({
            filename: decodeURIComponent(href.slice(readIdx + readMarker.length)),
            title: col.dataset.title || '',
            author: col.dataset.author || '',
            cover: img ? img.getAttribute('src') || '' : '',
            progress: col.dataset.progress ? parseFloat(col.dataset.progress) : null,
            // The lock badge encodes admin-only state in the server-rendered grid.
            access_level: col.querySelector('.book-lock') ? 'restricted' : 'standard',
        });
    });
}

function rerenderLibrary() {
    $('#library').empty().show();
    $('#emptyState').hide();
    loadedBooks.forEach(appendBookToLibrary);
}

// <== SEARCH ==>
// One box: every word must match the title, author, genre or one of your tags.
function applyFilters() {
    // Reset pagination
    offset = 0;
    allImagesLoaded = false;

    const q = ($('#librarySearch').val() || '').trim();
    currentFilters = q ? {q} : {};

    reloadLibrary();
}

const debouncedApplyFilters = debounce(applyFilters, 250);
$('#librarySearch').on('input', debouncedApplyFilters);
$('#librarySearch').on('keydown', function(e) {
    if (e.key === 'Enter') {
        applyFilters();
        this.blur();  // drops the phone keyboard so the results show
    } else if (e.key === 'Escape' && this.value) {
        e.stopPropagation();
        this.value = '';
        applyFilters();
    }
});


// <== FUNCTIONS FOR VIEWING AND EDITING METADATA ==>
function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function generateMetadataHtml(data, isUpload = false) {
    const isAuth = window.isAuthenticated;
    const isAdmin = (window.currentUserRole || '') === 'admin';
    // Admins can edit existing books; an uploader edits their own incoming book.
    const editable = isAdmin || isUpload;

    const ids = isUpload
        ? { title: 'upload-metadata-title', author: 'upload-metadata-author',
            genre: 'upload-metadata-genre' }
        : { title: 'metadata-title', author: 'metadata-author',
            genre: 'metadata-genre' };

    // --- Header: title and author act as the panel's heading ---
    // A textarea so long titles wrap and stay readable; autoGrow sizes it.
    const titleEl = editable
        ? `<textarea id="${ids.title}" class="meta-title-input" rows="1"
                     placeholder="Untitled">${escapeHtml(data.title || '')}</textarea>`
        : `<h2 id="${ids.title}" class="meta-title">${escapeHtml(data.title || 'Untitled')}</h2>`;

    const authorEl = editable
        ? `<input type="text" id="${ids.author}" class="meta-author-input"
                  value="${escapeHtml(data.author_display || data.author || '')}" placeholder="Author"
                  data-raw="${escapeHtml(data.author || '')}" data-shown="${escapeHtml(data.author_display || data.author || '')}">`
        : `<p id="${ids.author}" class="meta-author">${escapeHtml(data.author_display || data.author || 'Unknown author')}</p>`;

    // --- Cover with hover overlay for admins ---
    const coverChange = (isAdmin && !isUpload)
        ? `<button type="button" class="meta-cover__change"
                   data-action="change-cover" data-filename="${escapeHtml(data.filename)}">
              ${icon('camera')}<span>Change cover</span>
           </button>`
        : '';
    const cover = `
        <figure class="meta-cover${isAdmin && !isUpload ? ' meta-cover--editable' : ''}">
            <img id="cover-preview-image" src="${escapeHtml(data.cover)}"
                 alt="Cover of ${escapeHtml(data.title || 'this book')}">
            ${coverChange}
        </figure>
    `;

    // --- Always-shown genre field ---
    const genreField = `
        <label class="meta-field">
            <span class="meta-label">Genre</span>
            ${editable
                ? `<input type="text" id="${ids.genre}" class="meta-input"
                          value="${escapeHtml(data.genre || '')}"
                          placeholder="e.g. Fiction, Memoir">`
                : `<span id="${ids.genre}" class="meta-value">${escapeHtml(data.genre || '—')}</span>`}
        </label>
    `;

    // --- Admin-only access toggle (admins, existing books) ---
    const adminOnlyField = (isAdmin && !isUpload)
        ? `
            <label class="meta-field meta-checkbox-field">
                <input type="checkbox" id="metadata-admin-only"
                       ${data.access_level !== 'standard' ? 'checked' : ''}>
                <span class="meta-label">Private — only admins can see this book</span>
            </label>
          `
        : '';

    // --- Reading status (signed-in, existing books) ---
    const STATUSES = [['Unread', 'Unread'], ['In Progress', 'Reading'], ['Finished', 'Finished']];
    const statusField = (isAuth && !isUpload)
        ? `
            <div class="meta-field">
                <span class="meta-label" id="meta-status-label">Status</span>
                <div class="status-filter meta-status" role="radiogroup" aria-labelledby="meta-status-label">
                    ${STATUSES.map(([value, label]) => `
                        <button type="button" role="radio" data-status="${value}"
                                aria-checked="${(data.status || 'Unread') === value}">${label}</button>`).join('')}
                </div>
            </div>
          `
        : '';

    // --- Tags (new uploads included) ---
    const extraField = `
            <div class="meta-field">
                <span class="meta-label">Tags</span>
                ${isAuth
                    ? `<div class="tag-input-container">
                          <div class="tags-container" id="tags-container"></div>
                          <input type="text" id="tags-input"
                                 placeholder="Add a tag" aria-label="Add a tag">
                       </div>`
                    : `<span class="meta-value">${escapeHtml((data.tags || []).join(', ') || 'No tags yet')}</span>`}
            </div>
          `;

    // --- Footer: timestamp on the left, actions on the right ---
    const created = (!isUpload && data.created_at)
        ? `<span class="meta-footer-info">Added ${escapeHtml(formatAddedDate(data.created_at))}</span>`
        : `<span class="meta-footer-info"></span>`;

    const downloadButton = !isUpload
        ? `<a class="btn btn-ghost meta-download" href="${appUrl(`/download/${encodeURIComponent(data.filename)}`)}" download
              title="Download the EPUB">${icon('download')}<span>Download</span></a>`
        : '';
    const deleteButton = (isAdmin && !isUpload)
        ? `<button type="button" class="delete-book-button btn btn-danger"
                   data-action="delete-book" data-filename="${escapeHtml(data.filename)}">
              ${icon('trash-2')}<span>Delete</span>
           </button>`
        : '';
    const saveLabel = isUpload ? 'Add to library' : 'Save changes';
    const saveButton = isAuth
        ? (isUpload
            ? `<button type="button" class="save-button btn btn-primary"
                       data-action="save-new-book">
                  ${saveLabel}
               </button>`
            : `<button type="button" class="save-button btn btn-primary"
                       data-action="save-metadata" data-filename="${escapeHtml(data.filename)}">
                  ${saveLabel}
               </button>`)
        : '';

    return `
        <header class="meta-header">
            ${titleEl}
            ${authorEl}
        </header>
        <section class="meta-body">
            ${cover}
            <div class="meta-fields">
                ${statusField}
                ${genreField}
                ${extraField}
                ${adminOnlyField}
            </div>
        </section>
        <footer class="meta-footer">
            ${created}
            <div class="meta-footer-actions">
                ${downloadButton}
                ${deleteButton}
                ${saveButton}
            </div>
        </footer>
    `;
}

// A cover picked in the details panel, applied on Save. Tied to the book it
// was picked for and cleared whenever the panel opens or closes, so it can
// never be saved onto a different book.
let pendingCover = null;  // {filename, file}

// "2026-05-10 13:45:53" (UTC) -> "10 May 2026" in the reader's own locale.
function formatAddedDate(utcString) {
    const d = new Date(utcString.replace(' ', 'T') + 'Z');
    if (Number.isNaN(d.getTime())) return utcString.split(' ')[0];
    return d.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
}

function showMetadata(filename) {
    pendingCover = null;
    rememberFocus();
    const urlSafe = encodeURIComponent(filename);
    $.get(appUrl(`/book_metadata/${urlSafe}`), function(data) {
        $('#metadataContent').html(generateMetadataHtml(data));
        $('#metadataOverlay').css('display', 'flex').fadeIn();
        initializeTagInput('tags-input', 'tags-container', data.tags);
        snapshotPanel();
        focusFirstMetadataField();
    }).fail(function() {
        showToast("Couldn't open this book's details. Try again.", 'error');
    });
}

// The upload being reviewed in the panel: {upload_id, cover_path}. Closing the
// panel without adding the book discards the staged file on the server.
let pendingUpload = null;

function showUploadMetadata(data) {
    pendingCover = null;
    rememberFocus();
    pendingUpload = {upload_id: data.upload_id, cover_path: data.cover_path};
    $('#metadataContent').html(generateMetadataHtml(data, true));
    $('#metadataOverlay').css('display', 'flex').fadeIn();
    initializeTagInput('tags-input', 'tags-container');
    snapshotPanel();
    focusFirstMetadataField();
}

function discardPendingUpload() {
    if (!pendingUpload) return;
    const id = pendingUpload.upload_id;
    pendingUpload = null;
    fetch(appUrl(`/upload_book/${id}`), {method: 'DELETE'}).catch(() => {});
}

// Grow a textarea to fit its text (titles wrap instead of scrolling sideways).
function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
}
document.addEventListener('input', (e) => {
    if (e.target.matches?.('.meta-title-input')) autoGrow(e.target);
});
// The title is a single logical line: Enter saves instead of adding a newline.
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches?.('textarea.meta-title-input')) {
        e.preventDefault();
        document.querySelector('#metadataContent .save-button')?.click();
    }
});

// Touch devices: focusing an input pops up the keyboard over half the sheet,
// so only focus where there's a real keyboard already.
const COARSE_POINTER = window.matchMedia('(hover: none), (pointer: coarse)').matches;

function focusFirstMetadataField() {
    // The card opens as a book, not a form: no field is entered until you
    // tap one. Keyboard focus goes inside the dialog, on its close button.
    setTimeout(() => {
        const title = document.querySelector('#metadataContent .meta-title-input');
        if (title) autoGrow(title);
        if (!COARSE_POINTER) document.querySelector('.close-metadata')?.focus({preventScroll: true});
    }, 50);
}

// Unsaved-changes guard. A snapshot of the panel's fields is taken when it
// opens; closing with different values (or a pending cover, or an upload
// that hasn't been added) asks first.
let _panelSnapshot = null;
function panelState() {
    return JSON.stringify({
        fields: Array.from(document.querySelectorAll('#metadataContent input, #metadataContent textarea'))
            .map(el => el.type === 'checkbox' ? el.checked : el.value),
        tags: Array.from(document.querySelectorAll('#tags-container .tag')).map(t => t.textContent),
        status: $('.meta-status [aria-checked="true"]').data('status') || null,
    });
}
function snapshotPanel() { _panelSnapshot = panelState(); }
function panelIsDirty() {
    return Boolean(pendingUpload) || Boolean(pendingCover)
        || (_panelSnapshot !== null && panelState() !== _panelSnapshot);
}

// Close from Esc, the backdrop or ×: ask first if something would be lost.
function requestCloseMetadata() {
    if (!panelIsDirty()) return closeMetadataOverlay();
    if (document.querySelector('.discard-bar')) return;  // already asking
    const bar = document.createElement('div');
    bar.className = 'discard-bar';
    bar.setAttribute('role', 'alertdialog');
    bar.setAttribute('aria-label', 'Unsaved changes');
    const text = document.createElement('span');
    text.textContent = pendingUpload ? "This book hasn't been added yet." : 'You have unsaved changes.';
    const keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'btn btn-secondary';
    keep.textContent = 'Keep editing';
    keep.addEventListener('click', () => bar.remove());
    const discard = document.createElement('button');
    discard.type = 'button';
    discard.className = 'btn btn-danger';
    discard.textContent = pendingUpload ? 'Discard book' : 'Discard changes';
    discard.addEventListener('click', () => { bar.remove(); closeMetadataOverlay(); });
    bar.append(text, keep, discard);
    document.querySelector('.meta-footer').prepend(bar);
    keep.focus();
}

function closeMetadataOverlay() {
    _panelSnapshot = null;
    document.querySelector('.discard-bar')?.remove();
    pendingCover = null;
    discardPendingUpload();
    $('#metadataOverlay').fadeOut(150);
    restoreFocus();
}

// <== KEYBOARD + FOCUS ==>
// "/" search, "U" add a book, Esc closes whatever panel is open.
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (document.querySelector('.discard-bar')) document.querySelector('.discard-bar').remove();
        else if ($('#metadataOverlay').is(':visible')) requestCloseMetadata();
        else if ($('#loginOverlay').is(':visible')) closeLoginDialog();
        return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
    if ($('#metadataOverlay').is(':visible') || $('#loginOverlay').is(':visible')) return;
    if (e.key === '/') {
        e.preventDefault();
        document.getElementById('librarySearch')?.focus();
    } else if (e.key.toLowerCase() === 'u' && window.isAuthenticated) {
        e.preventDefault();
        document.getElementById('fileUploadInput').click();
    }
});

// While a panel is open, Tab cycles inside it; on close, focus returns to
// whatever opened it (e.g. the cover's Details button).
let _focusBeforePanel = null;
function rememberFocus() { _focusBeforePanel = document.activeElement; }
function restoreFocus() {
    if (_focusBeforePanel && document.contains(_focusBeforePanel)) _focusBeforePanel.focus();
    _focusBeforePanel = null;
}
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const panel = $('#metadataOverlay').is(':visible') ? document.querySelector('.metadata-content')
        : $('#loginOverlay').is(':visible') ? document.querySelector('.login-content') : null;
    if (!panel) return;
    const focusable = [...panel.querySelectorAll('a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])')]
        .filter(el => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (!panel.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
    }
});

function saveMetadata(filename) {
    // Determine if the current user is an admin.
    let isAdmin = window.currentUserRole && window.currentUserRole.toLowerCase() === 'admin';

    // For each metadata field, check if it is rendered as an input (editable) or as a span.
    const title = $('#metadata-title').is('input, textarea') ? $('#metadata-title').val() : $('#metadata-title').text().trim();
    // The author is shown as people write it ("Tony Judt"); left as shown,
    // it's saved as it was stored ("Judt, Tony").
    const authorEl = document.getElementById('metadata-author');
    let author = $('#metadata-author').is('input') ? $('#metadata-author').val() : $('#metadata-author').text().trim();
    if (authorEl && authorEl.dataset.shown !== undefined && author === authorEl.dataset.shown) author = authorEl.dataset.raw;
    const genre = $('#metadata-genre').is('input') ? $('#metadata-genre').val() : $('#metadata-genre').text().trim();

    // Include a tag that was typed but not yet confirmed with Enter.
    const pendingTag = ($('#tags-input').val() || '').trim();
    const metadata = {
        title,
        author,
        genre,
        tags: [
            ...Array.from($('#tags-container .tag')).map(tag =>
                tag.textContent.replace(/×/g, '').trim()
            ),
            ...(pendingTag ? [pendingTag] : []),
        ],
    };
    const status = $('.meta-status [aria-checked="true"]').data('status');
    if (status) metadata.status = status;

    // Access level is admin-only; the toggle only renders for admins. The
    // server ignores the field for non-admins regardless.
    if (isAdmin && $('#metadata-admin-only').length) {
        metadata.access_level = $('#metadata-admin-only').is(':checked') ? 'restricted' : 'standard';
    }

    const saveButton = $('.save-button');
    const originalText = saveButton.text();
    saveButton.text('Saving…');

    // If a new cover is selected, update it on the server first
    function updateCover() {
        if (pendingCover && pendingCover.filename === filename) {
            const formData = new FormData();
            formData.append('cover', pendingCover.file);
            formData.append('filename', filename);
            return fetch(appUrl('/update_cover'), {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => new Promise((_, reject) => reject(data.error)));
                }
                return response.json();
            })
            .then(data => {
                document.getElementById('cover-preview-image').src = data.cover;
                pendingCover = null;
                updateCoverEverywhere(filename, data);
            });
        } else {
            return Promise.resolve();
        }
    }

    updateCover().then(() => {
        $.ajax({
            url: appUrl(`/book_metadata/${filename}`),
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(metadata),
            success: function(response) {
                invalidateTagsCache();
                saveButton.text(originalText);
                _panelSnapshot = null;
                closeMetadataOverlay();
                showToast('Saved', 'success');
            },
            error: function(xhr, status, error) {
                const msg = (xhr.responseJSON && xhr.responseJSON.error) || "Couldn't save your changes. Try again.";
                showToast(msg, 'error');
                saveButton.text(originalText);
            }
        });
    }).catch(error => {
        showToast(typeof error === 'string' && error ? error : "Couldn't change the cover. Try a JPG or PNG.", 'error');
        saveButton.text(originalText);
    });
}

// × closes (a click on its icon counts); so does a click on the backdrop
// itself, not on the card.
$('#metadataOverlay .close-metadata').on('click', () => requestCloseMetadata());
$('#metadataOverlay').on('click', function(e) {
    if (e.target === this) requestCloseMetadata();
});

// After a cover change, swap the new (versioned) thumbnail URL into the
// book's card and into the mirror used to re-render the wall.
function updateCoverEverywhere(filename, urls) {
    const coverUrl = urls.thumb || urls.cover;
    const book = loadedBooks.find(b => b.filename === filename);
    if (book) book.cover = coverUrl;
    const readHref = appUrl(`/read/${encodeURIComponent(filename)}`);
    document.querySelectorAll(`a[href="${CSS.escape(readHref)}"]`).forEach(link => {
        const card = link.closest('.col-md-3');
        if (!card) return;
        const img = card.querySelector('img');
        if (img) img.src = coverUrl;
    });
}

// Delete moves the book to the trash on the server; the toast's Undo restores
// it. No confirm dialog: the action is reversible (for TRASH_RETENTION_DAYS).
async function deleteBook(filename) {
    const button = $('.delete-book-button');
    const originalText = button.text();
    button.text('Deleting…').prop('disabled', true);

    let title = filename;
    try {
        const response = await fetch(appUrl(`/book/${encodeURIComponent(filename)}`), {
            method: 'DELETE',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        title = data.title || title;
    } catch (err) {
        showToast(`Couldn't delete this book: ${err.message}`, 'error');
        button.text(originalText).prop('disabled', false);
        return;
    }

    // Drop the card from the wall, and from the in-memory mirror so a later
    // re-render doesn't bring it back. Keep both for Undo.
    const index = loadedBooks.findIndex(b => b.filename === filename);
    const removed = index !== -1 ? loadedBooks.splice(index, 1)[0] : null;
    rerenderLibrary();
    closeMetadataOverlay();

    showToast(`Deleted "${title}"`, 'info', {
        label: 'Undo',
        onClick: () => restoreBook(filename, title, removed, index),
    });
}

async function restoreBook(filename, title, removed, index) {
    try {
        const response = await fetch(appUrl(`/book/${encodeURIComponent(filename)}/restore`), {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (err) {
        showToast(`Couldn't restore "${title}". Try again.`, 'error');
        return;
    }
    if (removed) {
        loadedBooks.splice(Math.min(index, loadedBooks.length), 0, removed);
        rerenderLibrary();
    }
    showToast(`Restored "${title}"`, 'success');
}


// Status control in the details panel: a radio group of buttons.
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.meta-status [data-status]');
    if (!btn) return;
    btn.parentElement.querySelectorAll('[data-status]').forEach(b =>
        b.setAttribute('aria-checked', b === btn ? 'true' : 'false'));
});

// <== LONG-PRESS (touch) ==>
// Covers have no hover on phones: press and hold any book to open its details.
(function enableLongPress() {
    const SELECTOR = '#library .book';
    const HOLD_MS = 500;
    let timer = null, start = null, fired = false;
    document.addEventListener('touchstart', (e) => {
        const target = e.target.closest(SELECTOR);
        if (!target || e.touches.length !== 1 || e.target.closest('.book-button')) return;
        fired = false;
        start = {x: e.touches[0].clientX, y: e.touches[0].clientY};
        timer = setTimeout(() => {
            const link = target.querySelector('a[href*="/read/"]') || target.closest('a[href*="/read/"]');
            const filename = link && readFilenameFromHref(link.getAttribute('href'));
            if (!filename) return;
            fired = true;
            navigator.vibrate?.(10);
            showMetadata(filename);
        }, HOLD_MS);
    }, {passive: true});
    const cancel = () => { clearTimeout(timer); timer = null; };
    document.addEventListener('touchmove', (e) => {
        if (!timer || !start) return;
        const t = e.touches[0];
        if (Math.abs(t.clientX - start.x) > 10 || Math.abs(t.clientY - start.y) > 10) cancel();
    }, {passive: true});
    document.addEventListener('touchend', cancel, {passive: true});
    document.addEventListener('touchcancel', cancel, {passive: true});
    // The press shouldn't also open the book or the system's link menu.
    document.addEventListener('click', (e) => {
        if (fired && e.target.closest(SELECTOR)) {
            e.preventDefault();
            e.stopPropagation();
            fired = false;
        }
    }, true);
    document.addEventListener('contextmenu', (e) => {
        if (e.target.closest(SELECTOR) && matchMedia('(hover: none)').matches) e.preventDefault();
    });
})();

function readFilenameFromHref(href) {
    const marker = '/read/';
    const i = (href || '').indexOf(marker);
    return i === -1 ? null : decodeURIComponent(href.slice(i + marker.length));
}

// <== FUNCTIONS FOR TAGGING ==>

// Cache the user's tag list once per page load. invalidateTagsCache() forces a refresh.
async function fetchUserTags() {
    if (window._userTagsCache) return window._userTagsCache;
    if (!window.isAuthenticated) {
        window._userTagsCache = [];
        return [];
    }
    try {
        const r = await fetch(appUrl('/tags'));
        window._userTagsCache = r.ok ? await r.json() : [];
    } catch {
        window._userTagsCache = [];
    }
    return window._userTagsCache;
}

function invalidateTagsCache() {
    window._userTagsCache = null;
}

// Attaches a typeahead dropdown under `input`. Returns { handleKey, refresh }
// so the surrounding keydown handler can defer to it for Enter / arrows / Esc.
function attachTagAutocomplete(input, container) {
    const dropdown = document.createElement('div');
    dropdown.className = 'tag-suggestions';
    dropdown.style.display = 'none';
    input.insertAdjacentElement('afterend', dropdown);

    let visible = [];
    let highlight = 0;

    const takenLower = () => new Set(
        Array.from(container.getElementsByClassName('tag'))
            .map(t => t.textContent.replace(/×/g, '').trim().toLowerCase())
    );

    function render() {
        dropdown.innerHTML = '';
        if (visible.length === 0) {
            dropdown.style.display = 'none';
            return;
        }
        if (highlight >= visible.length) highlight = visible.length - 1;
        if (highlight < 0) highlight = 0;
        visible.forEach((name, i) => {
            const el = document.createElement('div');
            el.className = 'tag-suggestion' + (i === highlight ? ' active' : '');
            el.dataset.index = i;
            el.textContent = name;
            dropdown.appendChild(el);
        });
        dropdown.style.display = 'block';
    }

    async function refresh() {
        const all = await fetchUserTags();
        const query = input.value.trim().toLowerCase();
        const taken = takenLower();
        visible = all
            .filter(name => !taken.has(name.toLowerCase()))
            .filter(name => !query || name.toLowerCase().includes(query));
        render();
    }

    function pick(idx) {
        if (idx < 0 || idx >= visible.length) return;
        addTag(visible[idx], container);
        input.value = '';
        refresh();
    }

    input.addEventListener('input', refresh);
    input.addEventListener('focus', refresh);

    dropdown.addEventListener('mousedown', (e) => {
        // mousedown beats input-blur; lets us pick before the dropdown closes
        const item = e.target.closest('.tag-suggestion');
        if (item) {
            e.preventDefault();
            pick(parseInt(item.dataset.index, 10));
        }
    });

    document.addEventListener('mousedown', (e) => {
        if (e.target !== input && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });

    return {
        refresh,
        // Returns true if the key was consumed by the autocomplete.
        handleKey(e) {
            const open = dropdown.style.display !== 'none';
            if (!open) return false;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                highlight = Math.min(visible.length - 1, highlight + 1);
                render();
                return true;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                highlight = Math.max(0, highlight - 1);
                render();
                return true;
            }
            if (e.key === 'Escape') {
                dropdown.style.display = 'none';
                return true;
            }
            if (e.key === 'Enter' && visible.length > 0) {
                e.preventDefault();
                pick(highlight);
                return true;
            }
            return false;
        },
    };
}

function initializeTagInput(inputId, containerId, initialTags = []) {
    const input = document.getElementById(inputId);
    const container = document.getElementById(containerId);
    if (!input || !container) return;

    initialTags.forEach(tag => {
        if (tag.trim()) addTag(tag.trim(), container);
    });

    const ac = attachTagAutocomplete(input, container);

    input.addEventListener('keydown', function(e) {
        // Let the autocomplete consume Enter/arrows/Escape first when it's open
        if (ac.handleKey(e)) return;

        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            const value = this.value.trim();
            if (value) {
                addTag(value, container);
                this.value = '';
                ac.refresh();
            }
        } else if (e.key === 'Backspace' && !this.value) {
            const tags = container.getElementsByClassName('tag');
            if (tags.length) {
                container.removeChild(tags[tags.length - 1]);
                ac.refresh();
            }
        }
    });
}
function addTag(text, container) {
    const cleanText = text.replace(/×/g, '').trim();
    if (!cleanText) return;

    // Build via DOM nodes so user-supplied tag text is never interpreted as HTML.
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.appendChild(document.createTextNode(cleanText + ' '));

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'remove-tag';
    removeBtn.innerHTML = icon('x');
    removeBtn.setAttribute('aria-label', `Remove tag ${cleanText}`);
    removeBtn.addEventListener('click', () => tag.remove());
    tag.appendChild(removeBtn);

    container.appendChild(tag);
}


// <== FUNCTIONS FOR UPLOADING BOOKS AND COVERS ==>
// <== ADDING BOOKS ==>
// Stage the file, then review it in the panel before it's added.
async function stageUpload(file) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(appUrl('/upload_book'), {method: 'POST', body: formData});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Couldn't add this book.");
    return data;
}

async function confirmUpload(body) {
    const response = await fetch(appUrl('/upload_book_metadata'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Couldn't add the book. Try again.");
    return data.book;
}

// Put a newly added book at the front of the library and flash it.
function insertNewBook(book) {
    $('#emptyState').hide();
    $('.library-toolbar').prop('hidden', false);
    $('#library').show();
    loadedBooks.unshift(book);
    if (totalBooks != null) totalBooks += 1;
    offset += 1;  // keep infinite scroll from re-fetching it
    rerenderLibrary();
    const link = document.querySelector(`#library a[href="${CSS.escape(appUrl(`/read/${encodeURIComponent(book.filename)}`))}"]`);
    const card = link?.closest('.col-md-3');
    if (card) {
        card.classList.add('is-new');
        card.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
}

async function handleFileUpload(files) {
    const input = document.getElementById('fileUploadInput');
    const list = Array.from(files || []).filter(f => f.name);
    input.value = '';  // so choosing the same file again still triggers
    if (!list.length) return;

    // One at a time, so each book's details can be checked before it's added.
    if (list.length > 1) {
        showToast('Add books one at a time, so each can be checked.', 'error');
        return;
    }
    const toast = showToast(`Reading ${list[0].name}…`, 'info', null, {sticky: true});
    try {
        const data = await stageUpload(list[0]);
        dismissToast(toast);
        showUploadMetadata(data);
    } catch (err) {
        dismissToast(toast);
        showToast(navigator.onLine ? err.message
            : "Upload didn't finish. Check your connection and try again.", 'error');
    }
}

async function saveNewBook() {
    if (!pendingUpload) return;
    const field = id => {
        const $el = $('#' + id);
        return $el.is('input, textarea') ? $el.val() : $el.text().trim();
    };
    const pendingTag = ($('#tags-input').val() || '').trim();
    const body = {
        upload_id: pendingUpload.upload_id,
        cover_path: pendingUpload.cover_path,
        title: field('upload-metadata-title'),
        author: field('upload-metadata-author'),
        genre: field('upload-metadata-genre'),
        tags: [
            ...Array.from($('#tags-container .tag')).map(t => t.textContent.replace(/×/g, '').trim()),
            ...(pendingTag ? [pendingTag] : []),
        ],
    };
    const button = $('.save-button');
    button.text('Adding…').prop('disabled', true);
    try {
        const book = await confirmUpload(body);
        pendingUpload = null;  // it's in the library now; nothing to discard
        closeMetadataOverlay();
        insertNewBook(book);
        showToast(`Added "${book.title}"`, 'success');
    } catch (err) {
        button.text('Add to library').prop('disabled', false);
        showToast(err.message, 'error');
    }
}

// Drop EPUBs anywhere on the library page to add them.
if (window.isAuthenticated) enableDropZone(document.getElementById('dropZone'), files => handleFileUpload(files));

// Function to trigger the cover upload dialog
function triggerCoverUpload(filename) {
    const input = document.getElementById('coverUploadInput');
    input.dataset.filename = filename;
    input.value = '';  // so picking the same file twice still fires change
    input.click();
}

// Function to handle uploading the new cover image
async function handleCoverUpload(files) {
    if (files.length) {
        // Held until Save; tied to the book the picker was opened for.
        const filename = document.getElementById('coverUploadInput').dataset.filename;
        pendingCover = {filename, file: files[0]};
        let reader = new FileReader();
        reader.onload = function(e) {
            // Update the cover preview immediately with the new image
            document.getElementById('cover-preview-image').src = e.target.result;
        };
        reader.readAsDataURL(files[0]);
    }
}


// <== FUNCTIONS FOR AUTHENTICATING ==>
function showLoginDialog() {
    rememberFocus();
    $('#loginOverlay').css('display', 'flex').fadeIn();
    $('#username').focus();
}

function closeLoginDialog() {
    $('#loginOverlay').fadeOut();
    restoreFocus();
    $('#loginForm')[0].reset();
    $('#loginError').hide();
}

async function handleLogin(event) {
    event.preventDefault();

    const formData = new FormData(event.target);

    try {
        const response = await fetch(appUrl('/auth/login'), {
            method: 'POST',
            body: formData
        });
        const data = await response.json();

        if (response.ok) {
            location.reload();
        } else {
            $('#loginError').text(data.error).show();
        }
    } catch (error) {
        console.error('Login error:', error);
        $('#loginError').text("Couldn't reach the library. Try again.").show();
    }
}

// Close dialog when clicking outside or on close button
$('.close-login').on('click', () => closeLoginDialog());
$('.login-overlay').on('click', function(e) {
    if (e.target === this) closeLoginDialog();
});

// Prevent closing when clicking inside the login content
$('.login-content').on('click', function(e) {
    e.stopPropagation();
});