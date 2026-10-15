// Registers the service worker (see sw.js) and handles being offline:
// a banner on the library page, and books that aren't saved for offline
// reading are dimmed and explain themselves instead of opening a dead page.

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register(appUrl('/sw.js'), {scope: appUrl('/')})
            .catch((err) => console.warn('Service worker registration failed:', err));
    });
}

// Filenames whose book data is in the offline cache.
async function offlineBookFilenames() {
    if (!('caches' in window)) return new Set();
    const cache = await caches.open('books-v1');
    const prefix = appUrl('/load_book/');
    return new Set((await cache.keys())
        .map((req) => new URL(req.url).pathname)
        .filter((p) => p.startsWith(prefix))
        .map((p) => decodeURIComponent(p.slice(prefix.length))));
}

const READ_PATH = appUrl('/read/');
function readLinkFilename(link) {
    const path = new URL(link.href, location.href).pathname;
    return path.startsWith(READ_PATH)
        ? decodeURIComponent(path.slice(READ_PATH.length))
        : null;
}

// navigator.onLine only knows about the device's network link; it stays true
// on a dead Wi-Fi or when the server is down. Ping the server to be sure.
let isOffline = !navigator.onLine;
async function checkConnection() {
    if (!navigator.onLine) return false;
    try {
        const r = await fetch(appUrl('/healthz'), {cache: 'no-store'});
        return r.ok;
    } catch {
        return false;
    }
}

async function markOfflineAvailability() {
    const offline = isOffline;
    const saved = offline ? await offlineBookFilenames() : null;
    document.querySelectorAll('a[href*="/read/"]').forEach((link) => {
        const filename = readLinkFilename(link);
        if (!filename) return;
        const card = link.closest('.col-md-3, .shelf-slot, .continue-card') || link;
        card.classList.toggle('is-unavailable', offline && !saved.has(filename));
    });
}

async function updateOnlineState() {
    isOffline = !(await checkConnection());
    const banner = document.getElementById('offlineBanner');
    if (banner) banner.hidden = !isOffline;
    markOfflineAvailability();
}

window.addEventListener('online', updateOnlineState);
window.addEventListener('offline', updateOnlineState);
document.addEventListener('DOMContentLoaded', () => {
    updateOnlineState();
    // Infinite scroll and layout switches add cards; mark those too.
    const library = document.getElementById('library');
    if (library) {
        new MutationObserver(() => {
            if (isOffline) markOfflineAvailability();
        }).observe(library, {childList: true});
    }
});

// Offline, a book that was never opened here can't load. Say so instead of
// navigating to a page that can't work.
document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href*="/read/"]');
    if (!link || !isOffline) return;
    const card = link.closest('.is-unavailable');
    if (!card) return;
    e.preventDefault();
    if (typeof showToast === 'function') {
        showToast("This book isn't saved on this device yet. Open it once while online to read it offline.");
    }
}, true);
