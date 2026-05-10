let offset = 8;
let isLoading = false;
let allImagesLoaded = false;
let currentFilters = {};

function getBookTemplate(book) {
    return `
        <div class="col-md-3 mb-3">
            <div class="book">
                <div class="book-buttons">
                    <button class="book-button">
                        <a href="/download/${book.filename}" download>
                            <i class="fas fa-download"></i>
                        </a>
                    </button>
                    <button class="book-button" onclick="showMetadata('${book.filename}')">
                        <i class="fas fa-ellipsis-h"></i>
                    </button>
                </div>
                <a href="/read/${book.filename}">
                    <img src="${book.cover}" alt="cover" loading="lazy">
                </a>
            </div>
        </div>
    `;
}

$(window).scroll(function() {
    if (!isLoading && !allImagesLoaded && $(window).scrollTop() + $(window).height() >= $(document).height() - 100) {
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
    $('#loading').show();

    const queryParams = new URLSearchParams(currentFilters);
    
    $.get(`/load_more/${offset}?${queryParams.toString()}`, function(data) {
        if (data.length === 0) {
            allImagesLoaded = true;
            // Show empty state if no books are displayed
            if (offset === 0) {
                $('#emptyState').show();
                $('#library').hide();
            }
        } else {
            $('#emptyState').hide();
            $('#library').show();
            data.forEach(function(book) {
                $('#library').append(getBookTemplate(book));
            });
        }
        offset += 8;
        isLoading = false;
        $('#loading').hide();
    });
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

    // Clear existing books
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
                   onclick="triggerCoverUpload('${escapeHtml(data.filename)}')">
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
        ? `<button type="button" class="delete-book-button"
                   onclick="confirmDeleteBook('${escapeHtml(data.filename)}')">
              <i class="fas fa-trash"></i><span>Delete</span>
           </button>`
        : '';
    const saveLabel = isUpload ? 'Add to library' : 'Save changes';
    const saveButton = isAuth
        ? `<button type="button" class="save-button"
                   onclick="${isUpload
                       ? `saveNewBook('${escapeHtml(data.filename)}', '${escapeHtml(data.cover_path || '')}')`
                       : `saveMetadata('${escapeHtml(data.filename)}')`}">
              ${saveLabel}
           </button>`
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
    // Defer until after the fadeIn so focus actually lands on a visible input
    setTimeout(() => {
        const first = document.querySelector('#metadataContent .meta-title-input');
        if (first) first.focus();
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
            return fetch('/update_cover', {
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
            url: `/book_metadata/${filename}`,
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
                alert('Error saving metadata: ' + error);
                saveButton.text(originalText);
            }
        });
    }).catch(error => {
        alert('Error updating cover: ' + error);
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
        const response = await fetch(`/book/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        // Drop the card from the grid (matched via the read link's filename)
        const card = document.querySelector(
            `a[href="/read/${CSS.escape(filename)}"]`
        )?.closest('.col-md-3');
        if (card) card.remove();
        $('#metadataOverlay').fadeOut();
    } catch (err) {
        alert(`Failed to delete: ${err.message}`);
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
        const r = await fetch('/tags');
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
    const removeTagHandler = isFiltering 
        ? 'this.parentElement.remove(); applyFilters();' 
        : 'this.parentElement.remove()';

    const tag = document.createElement('span');
    tag.className = 'tag' + (cleanText === "Finished" ? ' finished-tag' : (cleanText === "In Progress" ? ' started-tag' : (cleanText === "Unread" ? ' unread-tag' : '')));
    tag.innerHTML = `
        ${cleanText}
        <span class="remove-tag" onclick="${removeTagHandler}">×</span>
    `;
    container.appendChild(tag);
}


// <== FUNCTIONS FOR UPLOADING BOOKS AND COVERS ==>
async function handleFileUpload(files) {
    if (files.length) {
        const file = files[0]; // For simplicity, we handle one file at a time.
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/upload_book', {
                method: 'POST',
                body: formData
            });
            if (!response.ok) {
                const errorData = await response.json();
                alert("Upload failed: " + errorData.error);
                return;
            }
            const data = await response.json();
            // Open the metadata overlay with pre-populated fields from the uploaded book.
            showUploadMetadata(data);
        } catch (error) {
            console.error("Error during file upload", error);
            alert("Error uploading file");
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
        url: '/upload_book_metadata', // Adjust this URL if necessary
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
            alert("Error saving new book: " + msg);
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
        const response = await fetch('/auth/login', {
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
        const response = await fetch('/auth/logout');
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