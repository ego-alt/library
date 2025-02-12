let currentBook = null;
let currentChapter = null;

let allChapters = [];
let currentChapterNum = 0;
let currentPagePosition = 0;
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
                            // Update TOC with actual chapter title if available
                            if (currentChapter.title) {
                                const tocItem = document.getElementById(`toc-item-${chapterNum}`);
                                if (tocItem) {
                                    tocItem.textContent = currentChapter.title;
                                }
                            }         
                            allChapters[chapterNum] = currentChapter;
                            if (chapterNum == currentChapterNum) {
                                document.getElementById('loading-spinner').style.display = 'none';
                                document.getElementById('reader-content').style.display = 'block';
                                displayChapter();

                                // Wait for next paint to ensure content is rendered
                                requestAnimationFrame(() => {
                                    window.scrollTo({
                                        top: currentPagePosition * document.documentElement.scrollHeight,
                                        behavior: 'instant'
                                    });
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
    
    // Display initial table of contents with placeholder titles
    const tocContent = document.getElementById('toc-content');
    tocContent.innerHTML = currentBook.table_of_contents.map((chapter_title, index) => `
        <div class="toc-item ${index === currentChapterNum ? 'active' : ''}" 
             onclick="jumpToChapter(${index})"
             id="toc-item-${index}">
            ${chapter_title}
        </div>
    `).join('');
}

function displayChapter() {
    const content = allChapters[currentChapterNum].content;
    document.getElementById('chapter-content').innerHTML = content;
    document.getElementById('chapter-number').textContent = 
        `Section ${currentChapterNum + 1} of ${currentBook.table_of_contents.length}`;
    
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
    if (currentChapterNum < currentBook.table_of_contents.length - 1) {
        currentChapterNum++;
        displayChapter();
        window.scrollTo({top: 0, behavior: 'instant'});
        saveBookmark();
    }
    
    if (currentChapterNum === currentBook.table_of_contents.length - 1) {
        fetch(`/tag_finished/${filename}`, {
            method: 'POST'
        }).catch(error => console.error('Error adding tag:', error));
    }
}

function prevChapter() {
    if (currentChapterNum > 0) {
        currentChapterNum--;
        displayChapter();
        window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'});
        saveBookmark();
    }
}

function jumpToChapter(index) {
    currentChapterNum = index;
    displayChapter();
    window.scrollTo({top: 0, behavior: 'instant'});
    document.getElementById('toc-menu').classList.remove('visible');
    
    // Update active state in TOC
    document.querySelectorAll('.toc-item').forEach((item, idx) => {
        item.classList.toggle('active', idx === index);
    });
    
    saveBookmark();
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
                    chapter_index: currentChapterNum,
                    position: position
                })
            }).catch(error => console.error('Error saving bookmark:', error));
            
            lastSaveTimeout = null;
        }, 1000); // Debounce save for 1 second
    }
}

function adjustFontSize(delta) {
    currentFontSize = Math.max(12, Math.min(24, currentFontSize + delta));
    document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');
    localStorage.setItem('readerFontSize', currentFontSize);
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
