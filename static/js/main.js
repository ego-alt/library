let offset = 10;
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
                    <img src="data:image/jpeg;base64, ${book.cover}" alt="cover">
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
        offset += 10;
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
    console.log(currentFilters);

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
    console.log("Current User Role:", window.currentUserRole);
    const isAdmin = (window.currentUserRole || "") === 'admin';
    console.log("isAdmin:", isAdmin);

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
                <img id="cover-preview-image" src="data:image/jpeg;base64, ${data.cover}" alt="cover thumbnail" style="max-width: 180px; border-radius: 8px;">
                ${isAdmin ? `<button class="book-button" style="position: absolute; top: 5px; right: 5px;" onclick="triggerCoverUpload('${data.filename}')">
                    <i class="fas fa-edit"></i>
                </button>` : ''}
            </div>
        </div>
    `;

    // Action buttons for saving changes.
    const actionButtons = `
        <div class="metadata-actions" style="justify-content: 'right';">
            ${isAuth 
                ? `<button class="save-button" onclick="${isUpload ? `saveNewBook('${data.filename}', '${data.cover_path}')` : `saveMetadata('${data.filename}')`}">Save Changes</button>`
                : ``}
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
                // Optionally update the preview again from server return
                document.getElementById('cover-preview-image').src = `data:image/jpeg;base64, ${data.new_cover}`;
                window.newCoverFile = null; // Clear the temporary file variable
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
    // Collect the metadata from the overlay inputs.
    const newFilename = $('#upload-metadata-filename').val(); // Get the new filename
    const metadata = {
        title: $('#upload-metadata-title').val(),
        author: $('#upload-metadata-author').val(),
        genre: $('#upload-metadata-genre').val(),
        original_filename: originalFilename, // Send the original filename
        new_filename: newFilename, // Send the new filename
        cover_path: cover_path
    };

    $.ajax({
        url: '/upload_book_metadata', // Adjust this URL if necessary
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(metadata),
        success: function(response) {
            alert("Book added successfully!");
            $('#metadataOverlay').fadeOut();
            location.reload();
        },
        error: function(xhr, status, error) {
            console.error("Error saving new book:", error);
            alert("Error saving new book: " + error);
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
        console.log('Attempting login...');
        const response = await fetch('/auth/login', {
            method: 'POST',
            body: formData
        });
        
        console.log('Response status:', response.status);
        const data = await response.json();
        console.log('Response data:', data);
        
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