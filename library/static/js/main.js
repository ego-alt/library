let offset = 8;
let isLoading = false;
let allImagesLoaded = false;
let currentFilters = {};
// View state — 'all' (every book, newest first) or 'mine' (only started, by last_read).
// Server renders the initial batch using window.initialView; localStorage may override it.
let currentView = window.initialView || 'all';
// Layout state — 'grid' (cover cards) or 'shelf' (cover-slice spines on a wooden shelf).
// Server always renders grid; JS swaps to shelf on load if that's the stored preference.
let currentLayout = localStorage.getItem('libraryLayout') === 'shelf' ? 'shelf' : 'grid';
// Mirror of every book currently displayed, in insertion order. Seeded from the
// server-rendered HTML and appended to by loadMoreImages, so toggling layouts
// can re-render without re-fetching.
const loadedBooks = [];
// Total books available for the current view+filter. Server seeds it on
// initial render; each /load_more response refreshes it via X-Total-Count.
// Used to cap the number of loading skeletons we render.
let totalBooks = (typeof window.totalBooks === 'number') ? window.totalBooks : null;

// Spine thickness is a log-scaled mapping of book length (uncompressed HTML
// bytes — a cheap proxy for word count, computed server-side). When length
// is missing (older payloads, empty/broken EPUBs), fall back to a stable
// per-filename hash so we still get visual variety.
const SPINE_MIN_W = 22;
const SPINE_MAX_W = 80;
const SPINE_MIN_BYTES = 30_000;     // ~novella
const SPINE_MAX_BYTES = 3_000_000;  // ~doorstopper
function spineWidth(book) {
    const len = book.length;
    if (typeof len === 'number' && len > 0) {
        const clamped = Math.max(SPINE_MIN_BYTES, Math.min(SPINE_MAX_BYTES, len));
        const t = Math.log(clamped / SPINE_MIN_BYTES) / Math.log(SPINE_MAX_BYTES / SPINE_MIN_BYTES);
        return Math.round(SPINE_MIN_W + t * (SPINE_MAX_W - SPINE_MIN_W));
    }
    let h = 0;
    for (let i = 0; i < book.filename.length; i++) {
        h = ((h << 5) - h + book.filename.charCodeAt(i)) | 0;
    }
    return 32 + (Math.abs(h) % 28); // 32–59 px fallback
}

// Spine height is purely cosmetic — derived from the filename so re-renders
// stay stable and adjacent books vary in height like a real shelf.
function spineHeight(filename) {
    let h = 0;
    for (let i = 0; i < filename.length; i++) {
        h = ((h << 5) - h + filename.charCodeAt(i) * 7) | 0;
    }
    return 230 + (Math.abs(h) % 71); // 230–300 px
}

function getSpineTemplate(book) {
    const urlSafe = encodeURIComponent(book.filename);
    const attrSafe = escapeHtml(book.filename);
    const coverSafe = escapeHtml(book.cover);
    const width = spineWidth(book);
    const height = spineHeight(book.filename);
    return `
        <div class="shelf-slot" style="width: ${width}px">
            <div class="book-spine"
                 style="height: ${height}px; background-image: url(${coverSafe})"
                 title="${attrSafe}">
                <a class="book-spine__link" href="${appUrl(`/read/${urlSafe}`)}" aria-label="${attrSafe}"></a>
                <div class="book-buttons">
                    <button class="book-button book-button--spine">
                        <a href="${appUrl(`/download/${urlSafe}`)}" download>
                            <i class="fas fa-download"></i>
                        </a>
                    </button>
                    <button class="book-button book-button--spine"
                            data-action="show-metadata" data-filename="${attrSafe}">
                        <i class="fas fa-ellipsis-h"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
}

function appendBookToLibrary(book) {
    const html = currentLayout === 'shelf' ? getSpineTemplate(book) : getBookTemplate(book);
    $('#library').append(html);
}

// Plank height — keep in sync with --plank-h in index.css. Used to position
// the per-row planks rendered by repaintShelfPlanks.
const SHELF_PLANK_H = 14;

// Draw a full-page-width plank under each row of spines. Detect rows by their
// shared bottom edge: with align-items:flex-end + uniform plank padding, every
// slot in a wrapped flex row resolves to the same offsetTop+offsetHeight.
function repaintShelfPlanks() {
    const lib = document.getElementById('library');
    if (!lib) return;
    lib.querySelectorAll('.shelf-plank').forEach(p => p.remove());
    if (currentLayout !== 'shelf') return;

    const rowBottoms = new Set();
    lib.querySelectorAll('.shelf-slot').forEach(slot => {
        rowBottoms.add(slot.offsetTop + slot.offsetHeight);
    });

    rowBottoms.forEach(bottom => {
        const plank = document.createElement('div');
        plank.className = 'shelf-plank';
        plank.style.top = (bottom - SHELF_PLANK_H) + 'px';
        lib.appendChild(plank);
    });
}

// Rows rewrap when the window resizes — repaint to keep planks aligned.
let _shelfPlankResizeTimer;
window.addEventListener('resize', () => {
    if (currentLayout !== 'shelf') return;
    clearTimeout(_shelfPlankResizeTimer);
    _shelfPlankResizeTimer = setTimeout(repaintShelfPlanks, 120);
});

function getBookTemplate(book) {
    // book.filename comes from the DB and could contain anything if a malicious
    // filename was placed in BOOK_DIR and imported via `flask import-books`.
    // - URL paths: encodeURIComponent (handles spaces and HTML-special chars)
    // - data-filename attribute: HTML-escape so attribute parsing stays safe
    // - JS handler: event delegation reads dataset.filename, never inline onclick
    const urlSafe = encodeURIComponent(book.filename);
    const attrSafe = escapeHtml(book.filename);
    const coverSafe = escapeHtml(book.cover);
    return `
        <div class="col-md-3 mb-3">
            <div class="book">
                <div class="book-buttons">
                    <button class="book-button">
                        <a href="${appUrl(`/download/${urlSafe}`)}" download>
                            <i class="fas fa-download"></i>
                        </a>
                    </button>
                    <button class="book-button" data-action="show-metadata" data-filename="${attrSafe}">
                        <i class="fas fa-ellipsis-h"></i>
                    </button>
                </div>
                <a href="${appUrl(`/read/${urlSafe}`)}">
                    <img src="${coverSafe}" alt="cover" loading="lazy">
                </a>
            </div>
        </div>
    `;
}

function nearPageBottom(thresholdPx = 100) {
    return $(window).scrollTop() + $(window).height() >= $(document).height() - thresholdPx;
}

/** Shelf view packs many spines per row, so the first batch often fits entirely in
 *  the viewport — no scroll event fires and /load_more never runs. Keep fetching
 *  until the document is tall enough to scroll (or everything is loaded). */
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
function loadMoreImages() {
    isLoading = true;
    const skeletons = appendSkeletons(computeSkeletonCount());
    repaintShelfPlanks();

    const queryParams = new URLSearchParams(currentFilters);
    queryParams.set('view', currentView);

    $.get(appUrl(`/load_more/${offset}?${queryParams.toString()}`), function(data, _status, jqXHR) {
        skeletons.forEach(el => el.remove());
        const reported = parseInt(jqXHR.getResponseHeader('X-Total-Count'), 10);
        if (!Number.isNaN(reported)) totalBooks = reported;

        if (data.length === 0) {
            allImagesLoaded = true;
            if (offset === 0) {
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
            repaintShelfPlanks();
        }
        offset += 8;
        isLoading = false;
        requestAnimationFrame(tryLoadMoreIfPageStillShort);
    }).fail(function() {
        skeletons.forEach(el => el.remove());
        isLoading = false;
        showToast('Could not load more books', 'error');
    });
}

const SKELETON_COUNT = 8;

function computeSkeletonCount() {
    // If we don't know the total yet (e.g. anonymous browse before first
    // /load_more response), assume a full page worth of cards.
    if (totalBooks == null) return SKELETON_COUNT;
    const selector = currentLayout === 'shelf'
        ? '#library .shelf-slot:not(.shelf-slot--skeleton)'
        : '#library .col-md-3:not(.book-skeleton-wrapper)';
    const displayed = document.querySelectorAll(selector).length;
    return Math.min(SKELETON_COUNT, Math.max(0, totalBooks - displayed));
}

function appendSkeletons(count) {
    const grid = document.getElementById('library');
    if (!grid || count <= 0) return [];
    grid.style.display = '';
    const created = [];
    for (let i = 0; i < count; i++) {
        const el = document.createElement('div');
        if (currentLayout === 'shelf') {
            el.className = 'shelf-slot shelf-slot--skeleton';
            el.style.width = (SPINE_MIN_W + Math.floor(Math.random() * (SPINE_MAX_W - SPINE_MIN_W))) + 'px';
            const inner = document.createElement('div');
            inner.className = 'book-spine book-spine--skeleton';
            inner.style.height = (230 + Math.floor(Math.random() * 71)) + 'px';
            el.appendChild(inner);
            el.setAttribute('aria-hidden', 'true');
        } else {
            el.className = 'col-md-3 mb-3 book-skeleton-wrapper';
            el.innerHTML = '<div class="book-skeleton" aria-hidden="true"></div>';
        }
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
        case 'delete-book':    confirmDeleteBook(filename); break;
        case 'save-metadata':  saveMetadata(filename); break;
        case 'save-new-book':  saveNewBook(filename, trigger.dataset.coverPath || ''); break;
    }
});


// <== TOAST NOTIFICATIONS ==>
// Non-blocking replacement for alert() — slides in bottom-right and auto-dismisses.
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) {
        // Fallback if toast container isn't on this page (e.g. reader.html)
        console.warn('showToast called without #toastContainer:', message);
        return;
    }
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.textContent = message;
    toast.addEventListener('click', () => dismissToast(toast));
    container.appendChild(toast);
    // Force a reflow so the entrance transition fires
    requestAnimationFrame(() => toast.classList.add('toast--shown'));
    setTimeout(() => dismissToast(toast), type === 'error' ? 6000 : 4000);
}

function dismissToast(toast) {
    if (!toast.parentNode) return;
    toast.classList.remove('toast--shown');
    toast.addEventListener(
        'transitionend',
        () => { if (toast.parentNode) toast.remove(); },
        { once: true },
    );
}

function renderEmptyState() {
    const $empty = $('#emptyState');
    const hasFilters = Object.keys(currentFilters).some(k => currentFilters[k] && currentFilters[k].length);
    if (currentView === 'mine' && !hasFilters) {
        $empty.find('h3').text("Your library is empty");
        $empty.find('p').text("Open a book to start reading and it'll show up here.");
    } else {
        $empty.find('h3').text("No books match your filters");
        $empty.find('p').text("Try adjusting your search criteria");
    }
    $empty.show();
}


// <== VIEW TOGGLE (All books vs My books) ==>
function toggleView() {
    currentView = currentView === 'mine' ? 'all' : 'mine';
    localStorage.setItem('libraryView', currentView);
    updateViewToggleUI();
    reloadLibrary();
}

function updateViewToggleUI() {
    const btn = document.getElementById('viewToggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    const isMine = currentView === 'mine';
    btn.classList.toggle('active', isMine);
    btn.setAttribute('aria-pressed', isMine ? 'true' : 'false');
    btn.title = isMine
        ? "Showing your library — click to browse all books"
        : "Show only books you've started reading";
    if (icon) icon.className = isMine ? 'fas fa-bookmark' : 'far fa-bookmark';
}

function reloadLibrary() {
    offset = 0;
    allImagesLoaded = false;
    loadedBooks.length = 0;
    $('#emptyState').hide();
    $('#library').empty().show();
    loadMoreImages();
}

// On page load: respect a stored view preference if it differs from what the
// server rendered. Causes a brief flash on first load when 'mine' is stored.
$(function() {
    const stored = localStorage.getItem('libraryView');
    if (window.isAuthenticated && stored && stored !== currentView) {
        currentView = stored;
        reloadLibrary();
    }
    updateViewToggleUI();

    // Mirror the initial grid HTML into loadedBooks so flipping to shelf doesn't
    // require a refetch. Then, if 'shelf' is the stored preference, swap layout.
    seedLoadedBooksFromDOM();
    applyLayoutClasses();
    if (currentLayout === 'shelf') rerenderLibrary();
    updateLayoutToggleUI();
    requestAnimationFrame(tryLoadMoreIfPageStillShort);
});


// <== LAYOUT TOGGLE (Grid vs Bookshelf) ==>
function seedLoadedBooksFromDOM() {
    document.querySelectorAll('#library .col-md-3').forEach((col) => {
        const link = col.querySelector('a[href*="/read/"]');
        const img = col.querySelector('img');
        if (!link || !img) return;
        const href = link.getAttribute('href') || '';
        const readMarker = '/read/';
        const readIdx = href.indexOf(readMarker);
        if (readIdx === -1) return;
        const rawLength = parseInt(col.dataset.length || '', 10);
        loadedBooks.push({
            filename: decodeURIComponent(href.slice(readIdx + readMarker.length)),
            cover: img.getAttribute('src') || '',
            length: Number.isFinite(rawLength) ? rawLength : 0,
        });
    });
}

function toggleLayout() {
    currentLayout = currentLayout === 'shelf' ? 'grid' : 'shelf';
    localStorage.setItem('libraryLayout', currentLayout);
    applyLayoutClasses();
    rerenderLibrary();
    updateLayoutToggleUI();
    requestAnimationFrame(tryLoadMoreIfPageStillShort);
}

function applyLayoutClasses() {
    const lib = $('#library');
    if (currentLayout === 'shelf') {
        lib.removeClass('row').addClass('library-shelf');
    } else {
        lib.removeClass('library-shelf').addClass('row');
    }
}

function rerenderLibrary() {
    $('#library').empty().show();
    $('#emptyState').hide();
    loadedBooks.forEach(appendBookToLibrary);
    repaintShelfPlanks();
}

function updateLayoutToggleUI() {
    const btn = document.getElementById('layoutToggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    const isShelf = currentLayout === 'shelf';
    btn.classList.toggle('active', isShelf);
    btn.setAttribute('aria-pressed', isShelf ? 'true' : 'false');
    btn.title = isShelf ? 'Switch to grid view' : 'Switch to bookshelf view';
    if (icon) icon.className = isShelf ? 'fas fa-th-large' : 'fas fa-grip-vertical';
}


// <== FUNCTIONS FOR FILTERING ==>
// Add filter handling
function applyFilters() {
    // Reset pagination
    offset = 0;
    allImagesLoaded = false;
    
    // Collect filter values
    currentFilters = {
        title: $('#filterTitle').val(),
        author: $('#filterAuthor').val(),
        genre: $('#filterGenre').val(),
        tags: [
            ...Array.from($('#filter-tags-container .tag')).map(tag =>
                tag.innerText.replace(/×/g, '').trim()
            ),
            $('#filterTags').val().trim() // Include text from the input box
        ].filter(tag => tag) // Filter out any empty strings
    };

    // Clear existing books (DOM + in-memory mirror)
    loadedBooks.length = 0;
    $('#library').empty();

    // Load filtered books
    loadMoreImages();
}

// Add event listeners for filter inputs
const debouncedApplyFilters = debounce(applyFilters, 300);
$('#filterTitle, #filterAuthor, #filterGenre').on('input', debouncedApplyFilters);
$('#filterTags').on('keydown', function(event) { 
    if (event.key === 'Enter') { 
        applyFilters();
    }
});

$('.filter-button').on('click', function() {
    $('#filterSidebar').toggleClass('active');
    $('#filterOverlay').fadeToggle();
});

$('#filterOverlay').on('click', function() {
    $('#filterSidebar').removeClass('active');
    $('#filterOverlay').fadeOut();
});

// Initialize the filter tags input
initializeTagInput('filterTags', 'filter-tags-container');


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
            genre: 'upload-metadata-genre', filename: 'upload-metadata-filename' }
        : { title: 'metadata-title', author: 'metadata-author',
            genre: 'metadata-genre' };

    // --- Header: title and author act as the panel's heading ---
    const titleEl = editable
        ? `<input type="text" id="${ids.title}" class="meta-title-input"
                  value="${escapeHtml(data.title || '')}" placeholder="Untitled">`
        : `<h2 id="${ids.title}" class="meta-title">${escapeHtml(data.title || 'Untitled')}</h2>`;

    const authorEl = editable
        ? `<input type="text" id="${ids.author}" class="meta-author-input"
                  value="${escapeHtml(data.author || '')}" placeholder="Author">`
        : `<p id="${ids.author}" class="meta-author">${escapeHtml(data.author || 'Unknown author')}</p>`;

    // --- Cover with hover overlay for admins ---
    const coverChange = isAdmin
        ? `<button type="button" class="meta-cover__change"
                   data-action="change-cover" data-filename="${escapeHtml(data.filename)}">
              <i class="fas fa-camera"></i><span>Change cover</span>
           </button>`
        : '';
    const cover = `
        <figure class="meta-cover${isAdmin ? ' meta-cover--editable' : ''}">
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

    // --- Tags (existing book) or filename (upload) ---
    const extraField = isUpload
        ? `
            <label class="meta-field meta-field--muted">
                <span class="meta-label">Filename</span>
                <input type="text" id="${ids.filename}"
                       class="meta-input meta-input--mono"
                       value="${escapeHtml(data.filename || '')}">
            </label>
          `
        : `
            <div class="meta-field">
                <span class="meta-label">Custom tags</span>
                ${isAuth
                    ? `<div class="tag-input-container">
                          <div class="tags-container" id="tags-container"></div>
                          <input type="text" id="tags-input"
                                 placeholder="Type and press Enter">
                       </div>`
                    : `<span class="meta-value">${escapeHtml((data.tags || []).join(', ') || 'No tags yet')}</span>`}
            </div>
          `;

    // --- Footer: timestamp on the left, actions on the right ---
    const created = (!isUpload && data.created_at)
        ? `<span class="meta-footer-info">Added ${escapeHtml(data.created_at.split(' ')[0])}</span>`
        : `<span class="meta-footer-info"></span>`;

    const deleteButton = (isAdmin && !isUpload)
        ? `<button type="button" class="delete-book-button btn btn-danger"
                   data-action="delete-book" data-filename="${escapeHtml(data.filename)}">
              <i class="fas fa-trash"></i><span>Delete</span>
           </button>`
        : '';
    const saveLabel = isUpload ? 'Add to library' : 'Save changes';
    const saveButton = isAuth
        ? (isUpload
            ? `<button type="button" class="save-button btn btn-primary"
                       data-action="save-new-book"
                       data-filename="${escapeHtml(data.filename)}"
                       data-cover-path="${escapeHtml(data.cover_path || '')}">
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
                ${genreField}
                ${extraField}
            </div>
        </section>
        <footer class="meta-footer">
            ${created}
            <div class="meta-footer-actions">
                ${deleteButton}
                ${saveButton}
            </div>
        </footer>
    `;
}

function showMetadata(filename) {
    $.get(`/book_metadata/${filename}`, function(data) {
        $('#metadataContent').html(generateMetadataHtml(data));
        $('#metadataOverlay').css('display', 'flex').fadeIn();
        initializeTagInput('tags-input', 'tags-container', data.tags);
        focusFirstMetadataField();
    });
}

function showUploadMetadata(data) {
    $('#metadataContent').html(generateMetadataHtml(data, true));
    $('#metadataOverlay').css('display', 'flex').fadeIn();
    focusFirstMetadataField();
}

function focusFirstMetadataField() {
    // Defer until after the fadeIn so focus actually lands on a visible input.
    // Place the caret at the end of the existing text rather than at the start.
    setTimeout(() => {
        const first = document.querySelector('#metadataContent .meta-title-input');
        if (!first) return;
        first.focus();
        const end = first.value.length;
        first.setSelectionRange(end, end);
    }, 50);
}

function closeMetadataOverlay() {
    $('#metadataOverlay').fadeOut(150);
}

// Close on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && $('#metadataOverlay').is(':visible')) {
        closeMetadataOverlay();
    }
});

function saveMetadata(filename) {
    // Determine if the current user is an admin.
    let isAdmin = window.currentUserRole && window.currentUserRole.toLowerCase() === 'admin';

    // For each metadata field, check if it is rendered as an input (editable) or as a span.
    const title = $('#metadata-title').is('input') ? $('#metadata-title').val() : $('#metadata-title').text().trim();
    const author = $('#metadata-author').is('input') ? $('#metadata-author').val() : $('#metadata-author').text().trim();
    const genre = $('#metadata-genre').is('input') ? $('#metadata-genre').val() : $('#metadata-genre').text().trim();

    const metadata = {
        title,
        author,
        genre,
        tags: Array.from($('#tags-container .tag')).map(tag =>
            tag.textContent.replace(/×/g, '').trim()
        )
    };

    const saveButton = $('.save-button');
    const originalText = saveButton.text();
    saveButton.text('Saving...');

    // If a new cover is selected, update it on the server first
    function updateCover() {
        if (window.newCoverFile) {
            const formData = new FormData();
            formData.append('cover', window.newCoverFile);
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
                window.newCoverFile = null;
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
                saveButton.text('Saved!');
                setTimeout(() => {
                    saveButton.text(originalText);
                    $('#metadataOverlay').fadeOut(200);
                }, 500);
            },
            error: function(xhr, status, error) {
                showToast('Error saving metadata: ' + error, 'error');
                saveButton.text(originalText);
            }
        });
    }).catch(error => {
        showToast('Error updating cover: ' + error, 'error');
        saveButton.text(originalText);
    });
}

$('.close-metadata, .metadata-overlay').on('click', function(e) {
    if (e.target === this) {
        $('#metadataOverlay').fadeOut();
    }
});

async function confirmDeleteBook(filename) {
    if (!confirm(`Permanently delete "${filename}"?\nThis removes the file from disk and cannot be undone.`)) {
        return;
    }

    const button = $('.delete-book-button');
    const originalText = button.text();
    button.text('Deleting...').prop('disabled', true);

    try {
        const response = await fetch(appUrl(`/book/${encodeURIComponent(filename)}`), {
            method: 'DELETE',
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        // Drop the card/spine from the library, and from the in-memory mirror
        // so a later layout switch doesn't resurrect it.
        const link = document.querySelector(
            `a[href="${CSS.escape(appUrl(`/read/${encodeURIComponent(filename)}`))}"]`
        );
        const card = link?.closest('.col-md-3, .shelf-slot');
        if (card) card.remove();
        const idx = loadedBooks.findIndex(b => b.filename === filename);
        if (idx !== -1) loadedBooks.splice(idx, 1);
        repaintShelfPlanks();
        $('#metadataOverlay').fadeOut();
    } catch (err) {
        showToast(`Failed to delete: ${err.message}`, 'error');
        button.text(originalText).prop('disabled', false);
    }
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
        // If this is the filter input, rerun the filter immediately
        if (container.id === 'filter-tags-container') applyFilters();
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

    const isFiltering = container.id === 'filter-tags-container';
    const statusClass = {
        'Finished': 'finished-tag',
        'In Progress': 'started-tag',
        'Unread': 'unread-tag',
    }[cleanText];

    // Build via DOM nodes so user-supplied tag text is never interpreted as HTML.
    const tag = document.createElement('span');
    tag.className = 'tag' + (statusClass ? ' ' + statusClass : '');
    tag.appendChild(document.createTextNode(cleanText + ' '));

    const removeBtn = document.createElement('span');
    removeBtn.className = 'remove-tag';
    removeBtn.textContent = '×';
    removeBtn.addEventListener('click', () => {
        tag.remove();
        if (isFiltering) applyFilters();
    });
    tag.appendChild(removeBtn);

    container.appendChild(tag);
}


// <== FUNCTIONS FOR UPLOADING BOOKS AND COVERS ==>
async function handleFileUpload(files) {
    if (files.length) {
        const file = files[0]; // For simplicity, we handle one file at a time.
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch(appUrl('/upload_book'), {
                method: 'POST',
                body: formData
            });
            if (!response.ok) {
                const errorData = await response.json();
                showToast("Upload failed: " + errorData.error, 'error');
                return;
            }
            const data = await response.json();
            // Open the metadata overlay with pre-populated fields from the uploaded book.
            showUploadMetadata(data);
        } catch (error) {
            console.error("Error during file upload", error);
            showToast("Error uploading file", 'error');
        }
    }
}

function saveNewBook(originalFilename, cover_path) {
    // Match createField(): admins get <input>, others get <span> — use .val() only for inputs.
    function uploadMetadataField(id) {
        const $el = $('#' + id);
        return $el.is('input') ? $el.val() : $el.text().trim();
    }
    const metadata = {
        title: uploadMetadataField('upload-metadata-title'),
        author: uploadMetadataField('upload-metadata-author'),
        genre: uploadMetadataField('upload-metadata-genre'),
        original_filename: originalFilename,
        new_filename: uploadMetadataField('upload-metadata-filename'),
        cover_path: cover_path
    };

    $.ajax({
        url: appUrl('/upload_book_metadata'),
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(metadata),
        success: function(response) {
            $('.save-button').text("Uploaded!");
            $('#metadataOverlay').fadeOut();
            location.reload();
        },
        error: function(xhr, status, error) {
            const msg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : error;
            console.error("Error saving new book:", msg);
            showToast("Error saving new book: " + msg, 'error');
        }
    });
}

// Function to trigger the cover upload dialog
function triggerCoverUpload(filename) {
    window.currentCoverBook = filename; // Store the book filename for later reference
    document.getElementById('coverUploadInput').click();
}

// Function to handle uploading the new cover image
async function handleCoverUpload(files) {
    if (files.length) {
        // Store the file globally so that the actual update happens on Save
        window.newCoverFile = files[0];
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
    $('#loginOverlay').css('display', 'flex').fadeIn();
    $('#username').focus();
}

function closeLoginDialog() {
    $('#loginOverlay').fadeOut();
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
        $('#loginError').text('An error occurred. Please try again.').show();
    }
}

async function handleLogout() {
    try {
        const response = await fetch(appUrl('/auth/logout'));
        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        console.error('Logout error:', error);
    }
}

// Close dialog when clicking outside or on close button
$('.close-login, .login-overlay').on('click', function(e) {
    if (e.target === this) {
        closeLoginDialog();
    }
});

// Prevent closing when clicking inside the login content
$('.login-content').on('click', function(e) {
    e.stopPropagation();
});