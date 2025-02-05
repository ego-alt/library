let currentBook = null;
let currentChapter = 0;
let currentFontSize = parseInt(localStorage.getItem('readerFontSize')) || 16;
let lastSaveTimeout = null;
const filename = window.location.pathname.split('/').pop();

// Initialize font size from localStorage
document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');

// Load book on page load
window.addEventListener('DOMContentLoaded', () => { 
    document.getElementById('loading-spinner').style.display = 'block';
    // Show controls immediately on load
    document.querySelector('.top-controls').classList.add('visible');
    
    fetch(`/load_book/${filename}`)
        .then(response => response.json())
        .then(data => {
            currentBook = data;
            currentChapter = 0;
            document.getElementById('loading-spinner').style.display = 'none';
            document.getElementById('reader-content').style.display = 'block';
            displayBook();
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('loading-spinner').style.display = 'none';
            document.getElementById('chapter-content').innerHTML = 
                '<div class="alert alert-danger">Error loading book. Please try again.</div>';
        });
});

function adjustFontSize(delta) {
    currentFontSize = Math.max(12, Math.min(24, currentFontSize + delta));
    document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');
    localStorage.setItem('readerFontSize', currentFontSize);
}

function saveBookmark() {
    if (!lastSaveTimeout) {
        lastSaveTimeout = setTimeout(() => {
            const position = window.scrollY / document.documentElement.scrollHeight;
            fetch(`/bookmark/${filename}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    chapter_index: currentChapter,
                    position: position
                })
            }).catch(error => console.error('Error saving bookmark:', error));
            
            lastSaveTimeout = null;
        }, 1000); // Debounce save for 1 second
    }
}

function displayBook() {
    document.getElementById('book-title').textContent = currentBook.title;
    document.getElementById('book-author').textContent = `by ${currentBook.author}`;
    
    // Display table of contents
    const tocContent = document.getElementById('toc-content');
    tocContent.innerHTML = currentBook.chapters.map((chapter, index) => `
        <div class="toc-item ${index === currentChapter ? 'active' : ''}" 
             onclick="jumpToChapter(${index})">
            ${chapter.title || `Chapter ${index + 1}`}
        </div>
    `).join('');
    
    // Load bookmark
    fetch(`/bookmark/${filename}`)
        .then(response => response.json())
        .then(data => {
            if (data.chapter_index !== undefined) {
                currentChapter = data.chapter_index;
                displayChapter();
                // Wait for content to load before scrolling
                setTimeout(() => {
                    window.scrollTo({
                        top: data.position * document.documentElement.scrollHeight,
                        behavior: 'instant'
                    });
                }, 100);
            } else {
                displayChapter();
            }
        })
        .catch(error => {
            console.error('Error loading bookmark:', error);
            displayChapter();
        });
}

function displayChapter() {
    const content = currentBook.chapters[currentChapter].content;
    document.getElementById('chapter-content').innerHTML = content;
    document.getElementById('chapter-number').textContent = 
        `Section ${currentChapter + 1} of ${currentBook.chapters.length}`;
    
    // Show controls on chapter load
    const controls = document.querySelector('.top-controls');
    controls.classList.add('visible');
    
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
    if (currentChapter < currentBook.chapters.length - 1) {
        currentChapter++;
        displayChapter();
        window.scrollTo({top: 0, behavior: 'instant'});
        saveBookmark();
    }
    
    if (currentChapter === currentBook.chapters.length - 1) {
        fetch(`/tag_finished/${filename}`, {
            method: 'POST'
        }).catch(error => console.error('Error adding tag:', error));
    }
}

function prevChapter() {
    if (currentChapter > 0) {
        currentChapter--;
        displayChapter();
        window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'});
        saveBookmark();
    }
}

function jumpToChapter(index) {
    currentChapter = index;
    displayChapter();
    window.scrollTo({top: 0, behavior: 'instant'});
    document.getElementById('toc-menu').classList.remove('visible');
    
    // Update active state in TOC
    document.querySelectorAll('.toc-item').forEach((item, idx) => {
        item.classList.toggle('active', idx === index);
    });
    
    saveBookmark();
}

// Toggle menu visibility
document.getElementById('menu-toggle').addEventListener('click', () => {
    document.getElementById('toc-menu').classList.toggle('visible');
});

// Close menu when clicking outside
document.addEventListener('click', (e) => {
    const menu = document.getElementById('toc-menu');
    const menuToggle = document.getElementById('menu-toggle');
    
    if (!menu.contains(e.target) && !menuToggle.contains(e.target) && menu.classList.contains('visible')) {
        menu.classList.remove('visible');
    }
});

// Add scroll event listener for bookmark saving
window.addEventListener('scroll', () => {
    saveBookmark();
});
