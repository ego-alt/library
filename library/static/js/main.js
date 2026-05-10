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
function generateMetadataHtml(data, isUpload = false) {
    const isAuth = window.isAuthenticated;
    const isAdmin = (window.currentUserRole || "") === 'admin';

    // Helper function to create a field.
    // Only admin users get an <input> so they can edit the field.
    // Non-admins (or guests) see a <span> with the value.
    const createField = (label, value, id) => `
        <div class="metadata-field" style="margin-bottom: 10px;">
            <strong>${label}:</strong>
            ${isAdmin 
                ? `<input type="text" value="${value}" id="${id}">` 
                : `<span class="metadata-value" id="${id}">${value}</span>`}
        </div>
    `;

    // Create fields for title, author, and genre.
    const titleField = createField('Title', data.title, isUpload ? 'upload-metadata-title' : 'metadata-title');
    const authorField = createField('Author', data.author, isUpload ? 'upload-metadata-author' : 'metadata-author');
    const genreField = createField('Genre', data.genre || '', isUpload ? 'upload-metadata-genre' : 'metadata-genre');

    // For uploading a new book, include a filename field.
    const extraField = isUpload 
        ? createField('Filename', data.filename, 'upload-metadata-filename')
        : `
            <div class="metadata-field" style="margin-bottom: 10px;">
                <strong>Custom Tags:</strong>
                ${isAuth 
                    ? `<div class="tag-input-container">
                        <div class="tags-container" id="tags-container"></div>
                        <input type="text" id="tags-input" placeholder="Type and press Enter">
                    </div>` 
                    : `<span class="metadata-value">${data.tags.join(', ') || ''}</span>`}
            </div>
        `;
    
    // Cover preview with an edit button if the user is authenticated
    const coverPreview = `
        <div class="metadata-cover" style="text-align: left;">
            <strong style="display: block; margin-bottom: 10px;">Cover Preview:</strong>
            <div style="position: relative; display: inline-block;">
                <img id="cover-preview-image" src="${data.cover}" alt="cover thumbnail" style="max-width: 180px; border-radius: 8px;">
                ${isAdmin ? `<button class="book-button" style="position: absolute; top: 5px; right: 5px;" onclick="triggerCoverUpload('${data.filename}')">
                    <i class="fas fa-edit"></i>
                </button>` : ''}
            </div>
        </div>
    `;

    // Action buttons. Admins on an existing book also get a destructive Delete.
    const deleteButton = (isAdmin && !isUpload)
        ? `<button class="delete-book-button" onclick="confirmDeleteBook('${data.filename}')">Delete Book</button>`
        : ``;
    const saveButton = isAuth
        ? `<button class="save-button" onclick="${isUpload ? `saveNewBook('${data.filename}', '${data.cover_path}')` : `saveMetadata('${data.filename}')`}">Save Changes</button>`
        : ``;
    const actionButtons = `
        <div class="metadata-actions">
            ${deleteButton}
            ${saveButton}
        </div>
    `;
    
    // Combine all parts into the final HTML.
    return `
        <div class="metadata-grid" style="display: flex; align-items: flex-start;">
            <div class="metadata-fields" style="flex: 1; margin-right: 20px;">
                ${titleField}
                ${authorField}
                ${genreField}
                ${extraField}
            </div>
            ${coverPreview}
        </div>
        ${actionButtons}
    `;
}

function showMetadata(filename) {
    $.get(`/book_metadata/${filename}`, function(data) {
        const metadataHtml = generateMetadataHtml(data);
        $('#metadataContent').html(metadataHtml);
        $('#metadataOverlay').css('display', 'flex').fadeIn();
        initializeTagInput('tags-input', 'tags-container', data.tags);
    });
}

function showUploadMetadata(data) {
    const metadataHtml = generateMetadataHtml(data, true);
    $('#metadataContent').html(metadataHtml);
    $('#metadataOverlay').css('display', 'flex').fadeIn();
}

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
function initializeTagInput(inputId, containerId, initialTags = []) {
    const input = document.getElementById(inputId);
    const container = document.getElementById(containerId);

    // Add initial tags
    initialTags.forEach(tag => {
        if (tag.trim()) addTag(tag.trim(), container);
    });
    
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            const value = this.value.trim();
            if (value) {
                addTag(value, container);
                this.value = '';
            }
        } else if (e.key === 'Backspace' && !this.value) {
            const tags = container.getElementsByClassName('tag');
            if (tags.length) {
                container.removeChild(tags[tags.length - 1]);
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