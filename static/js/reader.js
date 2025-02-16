let currentBook = null;
let currentChapter = null;

let allChapters = [];
let currentChapterNum = 0;
let currentPagePosition = 0;
let currentFontSize = parseInt(localStorage.getItem('readerFontSize')) || 16;
let lastSaveTimeout = null;
const filename = window.location.pathname.split('/').pop();

let selectedRange = null;
let hrefChapterMapping = {};
let chapterSentences = [];

// Initialize font size from localStorage
document.documentElement.style.setProperty('--reader-font-size', currentFontSize + 'px');

// Add CSS variables for highlight colors
document.documentElement.style.setProperty('--highlight-color', 'rgba(225, 204, 171)'); // Light mode
document.documentElement.style.setProperty('--highlight-color-dark', 'rgba(58, 109, 154, 0.6)'); // Dark mode

const style = document.createElement('style');
style.textContent = `
    .highlighted-text {
        background-color: var(--highlight-color);
    }
    .dark-mode .highlighted-text {
        background-color: var(--highlight-color-dark);
    }
`;
document.head.appendChild(style);

// Add CSS for the overlay
const overlayStyle = document.createElement('style');
overlayStyle.textContent = `
    .search-overlay {
        display: none;
        position: absolute;
        z-index: 1000;
    }
    .search-overlay.active {
        display: block;
    }
    .search-container {
        position: relative;
        width: 300px;
        box-shadow: 0 2px 8px var(--overlay-box-shadow);
        background: var(--background-color);
        border-radius: 4px;
        overflow: hidden;
        transition: width 0.3s ease-out;
    }
    .drag-handle {
        position: absolute;
        top: 0;
        right: 0;
        width: 20px;
        height: 20px;
        cursor: move;
        z-index: 1001;
    }
    .search-container.expanded {
        width: 600px;
    }
    .search-input-container {
        padding: 8px;
    }
    .search-input {
        width: 100%;
        padding: 4px 8px;
        border: 1px solid var(--toc-item-highlight);
        border-radius: 4px;
        background: var(--background-color);
        color: var(--text-color-dark);
        font-size: 14px;
    }
    .search-input:focus {
        outline: none;
    }
    .dark-mode .search-input {
        border-color: var(--text-color-dark);
    }
    .search-response-container {
        max-height: 0;
        overflow: hidden;
        transition: max-height 0.3s ease-out;
        border-top: 1px solid var(--input-field-border);
    }
    .search-response-container.active {
        max-height: 300px;
        overflow-y: auto;
    }
    .search-response {
        padding: 4px 16px 12px;
        color: var(--text-color-dark);
        font-size: 14px;
        line-height: 1.5;
    }
    .temp-highlight {
        background-color: rgba(225, 204, 171);
        display: inline;
        box-decoration-break: clone;
        -webkit-box-decoration-break: clone;
        padding: 0.16em 0;
        margin: -0.16em 0;
        padding-right: 0.25em;
        margin-right: -0.25em;
    }
    .dark-mode .temp-highlight {
        background-color: rgba(58, 109, 154, 0.6);
    }
    .thinking-animation {
        color: var(--text-color-dark);
        font-size: 14px;
        padding: 4px 16px 12px;
        opacity: 0.7;
    }
`;
document.head.appendChild(overlayStyle);

// Initialize overlay and event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Add overlay HTML with drag handle
    const overlay = document.createElement('div');
    overlay.className = 'search-overlay';
    overlay.innerHTML = `
        <div class="search-container">
            <div class="drag-handle"></div>
            <div class="search-input-container">
                <input type="text" class="search-input" placeholder="Ask a quick question...">
            </div>
            <div class="search-response-container">
                <div class="search-response"></div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Add drag functionality
    const dragHandle = overlay.querySelector('.drag-handle');
    let isDragging = false;
    let currentX;
    let currentY;
    let initialX;
    let initialY;

    dragHandle.addEventListener('mousedown', (e) => {
        isDragging = true;
        initialX = e.clientX - overlay.offsetLeft;
        initialY = e.clientY - overlay.offsetTop;
    });

    document.addEventListener('mousemove', (e) => {
        if (isDragging) {
            e.preventDefault();
            currentX = e.clientX - initialX;
            currentY = e.clientY - initialY;
            
            // Keep overlay within viewport bounds
            const bounds = overlay.getBoundingClientRect();
            currentX = Math.max(0, Math.min(currentX, window.innerWidth - bounds.width));
            currentY = Math.max(0, Math.min(currentY, window.innerHeight - bounds.height));
            
            overlay.style.left = currentX + 'px';
            overlay.style.top = currentY + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
    });

    // Handle overlay input
    document.querySelector('.search-input').addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' || e.key === 'Escape') {
            if (e.key === 'Escape') {
                console.log('Closing overlay');
                closeOverlay();
            } else if (e.key === 'Enter') {
                const userInput = e.target.value.trim();
                
                // Get the highlighted text from the temp-highlight span
                const tempHighlight = document.querySelector('.temp-highlight');
                const highlightedText = tempHighlight ? tempHighlight.textContent.trim() : '';
                
                console.log('Selected text:', highlightedText);
                console.log('User input:', userInput);
                
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
                    const sentences = chapterSentences
                        .slice(0, currentChapterNum + 1)
                        .filter(Array.isArray)
                        .flat();

                    const payload = {
                        context: highlightedText,
                        question: userInput,
                        chapter_sentences: sentences
                    };
                    console.log('Full payload being sent:', payload);
                    const response = await fetch('/ask_question', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json',},
                        body: JSON.stringify(payload)
                    });
                    
                    const data = await response.json();
                    console.log('Claude Sonnet 3.5 answer:', data.answer);
                    
                    // Clear thinking animation
                    clearInterval(thinkingAnimation);
                    responseElement.className = 'search-response';
                    responseElement.textContent = data.answer;
                    
                    // Only expand if answer is over 100 characters
                    if (data.answer.length > 50) {
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

    // Close overlay when clicking outside
    document.addEventListener('click', (e) => {
        const overlay = document.querySelector('.search-overlay');
        if (overlay.classList.contains('active') && 
            !overlay.contains(e.target) && 
            e.target.tagName !== 'INPUT') {
            closeOverlay();
        }
    });
});

// Handle keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'd' || e.key === 'l')) {
        e.preventDefault();
        
        const selection = window.getSelection();
        const selectedString = selection.toString().trim();
        
        if (!selection.rangeCount || !selectedString) return;
        
        try {
            // Store the selected range and create highlight
            selectedRange = selection.getRangeAt(0).cloneRange();
            const tempHighlight = document.createElement('span');
            tempHighlight.className = 'temp-highlight';
            selectedRange.surroundContents(tempHighlight);
            
            // Prepare overlay
            const overlay = document.querySelector('.search-overlay');
            const responseContainer = document.querySelector('.search-response-container');
            const container = document.querySelector('.search-container');
            const input = overlay.querySelector('.search-input');
            
            overlay.classList.remove('active', 'define-mode');
            responseContainer.classList.remove('active');
            container.classList.remove('expanded');
            
            // Position overlay
            const rect = tempHighlight.getBoundingClientRect();
            overlay.style.top = `${window.scrollY + rect.bottom + 10}px`;
            overlay.style.left = `${rect.left}px`;
            
            if (e.key === 'k') {
                // Question mode
                input.value = '';
                input.placeholder = 'Ask a quick question...';
                requestAnimationFrame(() => {
                    overlay.classList.add('active');
                    input.focus();
                });
            } else if (e.key === 'd') {
                // Definition mode
                overlay.classList.add('active', 'define-mode');
                responseContainer.classList.add('active');
                handleDefinitionRequest(selectedString, tempHighlight);
            } else if (e.key === 'l') {
                // Translation mode
                overlay.classList.add('active', 'define-mode'); // Reuse define-mode to hide input
                responseContainer.classList.add('active');
                handleTranslationRequest(selectedString, tempHighlight);
            }
        } catch (error) {
            console.error('Error handling text selection:', error);
        }
    }
});

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
                            hrefChapterMapping[currentChapter.href] = chapterNum;
                            processChapter(currentChapter);

                            // Remove unprocessed state and update title if available
                            const tocItem = document.getElementById(`toc-item-${chapterNum}`);
                            if (tocItem) {
                                tocItem.classList.remove('unprocessed');
                                if (currentChapter.title) {
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
    
    // Display initial table of contents with placeholder titles and greyed out state
    const tocContent = document.getElementById('toc-content');
    tocContent.innerHTML = currentBook.table_of_contents.map((chapter_title, index) => `
        <div class="toc-item ${index === currentChapterNum ? 'active' : ''} unprocessed" 
             onclick="jumpToChapter(${index})"
             id="toc-item-${index}">
            ${chapter_title}
        </div>
    `).join('');
}

function updateProgressBar() {
    const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
    const position = Math.min(1, window.scrollY / scrollHeight);
    document.getElementById('chapter-progress').style.width = `${position * 100}%`;
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

function displayChapter() {
    const content = allChapters[currentChapterNum].content;
    document.getElementById('chapter-content').innerHTML = content;
    document.getElementById('chapter-number').textContent = 
        `Section ${currentChapterNum + 1} of ${currentBook.table_of_contents.length}`;
    
    // Initialize progress bar position
    updateProgressBar();
    
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
        updateProgressBar();
        // Update active state in TOC
        document.querySelectorAll('.toc-item').forEach((item, idx) => {
            item.classList.toggle('active', idx === currentChapterNum);
        });
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
        updateProgressBar();
        // Update active state in TOC
        document.querySelectorAll('.toc-item').forEach((item, idx) => {
            item.classList.toggle('active', idx === currentChapterNum);
        });
        saveBookmark();
    }
}

function jumpToChapter(index) {
    currentChapterNum = index;
    displayChapter();
    window.scrollTo({top: 0, behavior: 'instant'});
    updateProgressBar();
    document.getElementById('toc-menu').classList.remove('visible');
    
    // Update active state in TOC
    document.querySelectorAll('.toc-item').forEach((item, idx) => {
        item.classList.toggle('active', idx === index);
    });
    
    saveBookmark();
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

// Update scroll event listener to handle both functions
window.addEventListener('scroll', () => {
    updateProgressBar();
    saveBookmark();
});

// Add this new function to handle chapter links
function handleChapterLink(element) {
    const href = element.getAttribute('chapter-link');
    const sectionId = element.getAttribute('section-link');
    const targetChapter = hrefChapterMapping[href];
    
    jumpToChapter(targetChapter);
    
    if (sectionId) {
        requestAnimationFrame(() => {
            const targetElement = document.getElementById(sectionId);
            if (targetElement) {
                const rect = targetElement.getBoundingClientRect();
                const absoluteTop = window.pageYOffset + rect.top;
                // Calculate offset based on current font size
                const offset = currentFontSize * 2; // roughly one line height
                
                window.scrollTo({top: absoluteTop - offset, behavior: 'instant'});
            }
        });
    }
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

function processChapter(chapter) {
    console.log(`Processing chapter ${chapter.index}:`, {
        title: chapter.title,
        contentLength: chapter.content.length
    });

    // Use DOMParser for safer HTML parsing
    const parser = new DOMParser();
    const doc = parser.parseFromString(chapter.content, 'text/html');
    const text = doc.body.textContent
    
    // More sophisticated sentence splitting
    const sentenceRegex = /[^.!?]+(?:[.!?](?!['"]?\s|$)[^.!?]*)*[.!?]*/g;
    const sentences = text.match(sentenceRegex) || [];
    // Filter out empty or whitespace-only sentences and normalize whitespace
    const validSentences = sentences
        .map(s => s.trim().replace(/\s+/g, ' ')) // normalize whitespace
        .filter(s => s.length > 0);
        
    // Store sentences for this chapter at its index
    chapterSentences[chapter.index] = validSentences;
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
        
        // Only expand if result is over 100 characters
        if (result.length > 50) {
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
    handleTextRequest(selectedString, tempHighlight, '/define_word', 'Looking up definition...');
}

function handleTranslationRequest(selectedString, tempHighlight) {
    handleTextRequest(selectedString, tempHighlight, '/translate_text', 'Translating...');
}
