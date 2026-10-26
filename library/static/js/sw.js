// Offline support for the library.
//
// Two caches:
//   shell — pages, our static files (fonts and vendor scripts included), and small JSON responses.
//           Network-first for pages and JSON (fresh when online, cached when
//           not); cache-first for versioned assets.
//   books — the streamed book data (/load_book) and its images. A book's
//           data is keyed by ?v=<file mtime>, so it's served straight from
//           cache until the EPUB changes. The most recently opened MAX_BOOKS
//           stay available offline; older ones are evicted.
//   covers — cover images, capped at MAX_COVERS (oldest evicted).
//
// Served from the app root (see routes/pwa.py), so the scope is the whole
// mount: "/" standalone, "/library/" behind the dashboard proxy.

const SHELL_CACHE = 'shell-v32';
const BOOKS_CACHE = 'books-v1';
const COVERS_CACHE = 'covers-v1';
const COMICS_CACHE = 'comics-v1';
const MAX_BOOKS = 12;
const MAX_ISSUES = 12;   // comic issues kept offline, like books
const MAX_COVERS = 400;
const ROOT = new URL(self.registration.scope).pathname;  // always ends in "/"

// Never cached: auth, file downloads, the JSON APIs that change things, and the worker itself.
const PASSTHROUGH = ['auth/', 'download/', 'comics/api/', 'api/', 'sw.js', 'healthz'];
// Pages that need the server (downloads and settings).
const ONLINE_ONLY = ['downloads'];
// The look of every page, cached at install so the first offline launch
// isn't unstyled.
const SHELL_ASSETS = [
    'static/css/base.css', 'static/css/tokens.css', 'static/css/controls.css', 'static/css/index.css',
    'static/css/comics.css', 'static/css/manage.css', 'static/css/settings.css', 'static/css/reader.css', 'static/css/comic_reader.css',
    'static/js/app_root.js', 'static/js/signed_out.js', 'static/js/darkmode.js', 'static/js/ui.js', 'static/js/main.js',
    'static/js/pwa.js', 'static/js/comics.js', 'static/js/get.js', 'static/js/import.js', 'static/js/settings.js', 'static/js/reader.js', 'static/js/read_aloud.js', 'static/js/comic_reader.js',
    'static/vendor/jquery-3.6.0.min.js', 'static/fonts/inter/inter.css', 'static/fonts/inter/inter-latin.woff2', 'static/fonts/literata/literata.css', 'static/fonts/literata/literata-latin-wght-normal.woff2', 'static/fonts/literata/literata-latin-wght-italic.woff2',
    'static/icons.svg',
];
// JSON the library and reader read; cached so the last view works offline.
const JSON_ROUTES = ['load_more/', 'book_metadata/', 'tags', 'bookmark/'];

self.addEventListener('install', (event) => {
    // Warm the shell so the library opens offline even before a second visit.
    event.waitUntil(
        caches.open(SHELL_CACHE).then((cache) =>
            Promise.all([ROOT, `${ROOT}manifest.webmanifest`, ...SHELL_ASSETS.map((a) => ROOT + a)].map((url) =>
                cache.add(url).catch(() => {})
            ))
        ).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys.filter((k) => ![SHELL_CACHE, BOOKS_CACHE, COVERS_CACHE, COMICS_CACHE].includes(k))
                .map((k) => caches.delete(k))
        )).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);

    if (url.origin !== self.location.origin || !url.pathname.startsWith(ROOT)) return;
    const path = url.pathname.slice(ROOT.length);

    if (PASSTHROUGH.some((p) => path.startsWith(p))) return;

    if (request.mode === 'navigate') {
        // A book or issue that was never opened here can't work offline, and
        // Get, Downloads and Settings need the server: say so rather than
        // falling back to the library.
        if (path.startsWith('read/')) {
            event.respondWith(networkFirst(request, SHELL_CACHE).catch(() => offlinePage("This book isn't saved on this device yet.<br>Open it once while online to read it offline.")));
        } else if (path.startsWith('comics/read/')) {
            event.respondWith(networkFirst(request, SHELL_CACHE).catch(() => offlinePage("This issue isn't saved on this device yet.<br>Open it once while online to read it offline.")));
        } else if (ONLINE_ONLY.includes(path.split(/[/?]/)[0])) {
            event.respondWith(fetch(request).catch(() => offlinePage("You're offline.<br>Downloads and Settings need a connection.")));
        } else {
            event.respondWith(networkFirst(request, SHELL_CACHE, path.startsWith('comics/') ? `${ROOT}comics/` : ROOT));
        }
    } else if (/^comics\/issue\/\d+\/page\//.test(path)) {
        event.respondWith(comicPage(request, url, path));
    } else if (/^comics\/issue\/\d+\/cover/.test(path)) {
        event.respondWith(cover(request, url));
    } else if (path.startsWith('comics/issue/')) {
        return;  // downloads
    } else if (path.startsWith('load_book/')) {
        event.respondWith(bookData(request, url));
    } else if (path.startsWith('book_asset/')) {
        event.respondWith(staleWhileRevalidate(request, BOOKS_CACHE));
    } else if (path.startsWith('cover/')) {
        event.respondWith(cover(request, url));
    } else if (path.startsWith('static/') || path === 'manifest.webmanifest') {
        event.respondWith(staleWhileRevalidate(request, SHELL_CACHE));
    } else if (JSON_ROUTES.some((p) => path.startsWith(p))) {
        event.respondWith(networkFirst(request, SHELL_CACHE));
    }
});

// Pages and JSON: fresh from the network; the cached copy only when offline.
// A non-OK reply (e.g. the dashboard asking you to sign in) is passed through.
async function networkFirst(request, cacheName, fallbackUrl) {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
    } catch (err) {
        const cached = await cache.match(request)
            || (fallbackUrl && await cache.match(fallbackUrl));
        if (cached) return cached;
        throw err;
    }
}

function offlinePage(message) {
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline · Shelves</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
         box-sizing: border-box; font: 16px/1.5 Inter, -apple-system, sans-serif;
         background: #f6f4ef; color: #1f1d1a; text-align: center; }
  @media (prefers-color-scheme: dark) { body { background: #141210; color: #eadfca; } }
  a { color: inherit; }
</style></head><body><main>
<p>${message}</p>
<p><a href="${ROOT}">Back to library</a></p>
</main></body></html>`;
    return new Response(html, {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8'}});
}

async function staleWhileRevalidate(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);
    const network = fetch(request).then((response) => {
        if (response.ok) cache.put(request, response.clone());
        return response;
    }).catch(() => cached);
    return cached || network;
}

// Covers: versioned URLs never change, so cache-first; keep the newest
// MAX_COVERS and drop older versions of the same cover at the same width.
async function cover(request, url) {
    const cache = await caches.open(COVERS_CACHE);
    const cached = await cache.match(request);
    if (cached && url.searchParams.has('v')) return cached;
    try {
        const response = await fetch(request);
        if (response.ok) {
            const keys = await cache.keys();
            const width = url.searchParams.get('w');
            await Promise.all(keys
                .filter((k) => {
                    const u = new URL(k.url);
                    return u.pathname === url.pathname && u.searchParams.get('w') === width
                        && k.url !== request.url;
                })
                .map((k) => cache.delete(k)));
            await cache.put(request, response.clone());
            if (keys.length >= MAX_COVERS) {
                await Promise.all(keys.slice(0, keys.length - MAX_COVERS + 1)
                    .map((k) => cache.delete(k)));
            }
        }
        return response;
    } catch (err) {
        if (cached) return cached;
        throw err;
    }
}

// A whole book as NDJSON. Cache-first by versioned URL; on a miss, stream it
// to the reader while a copy is written to the cache.
async function bookData(request, url) {
    const cache = await caches.open(BOOKS_CACHE);
    const cached = await cache.match(request);
    if (cached) {
        markOpened(cache, url.pathname);
        return cached;
    }
    const response = await fetch(request);
    if (response.ok && url.searchParams.has('v')) {
        const copy = response.clone();
        // Write after the stream finishes; don't hold up the reader.
        copy.blob().then((body) => storeBook(cache, request, url, new Response(body, {
            headers: {'Content-Type': 'application/x-ndjson'},
        }))).catch(() => {});
    }
    return response;
}

// When each saved book was last opened, keyed by its /load_book path. Lives
// in the books cache as a small JSON entry; drives least-recently-opened
// eviction without ever taking a book out of the cache to re-order it.
const OPENED_KEY = `${ROOT}__opened.json`;

async function readOpened(cache) {
    const res = await cache.match(OPENED_KEY);
    try { return res ? await res.json() : {}; } catch { return {}; }
}

async function markOpened(cache, bookPath) {
    const opened = await readOpened(cache);
    opened[bookPath] = Date.now();
    await cache.put(OPENED_KEY, new Response(JSON.stringify(opened), {
        headers: {'Content-Type': 'application/json'},
    }));
    return opened;
}

async function storeBook(cache, request, url, response) {
    const bookPath = url.pathname;  // .../load_book/<filename>
    const keys = await cache.keys();
    // Drop older versions of this same book.
    await Promise.all(keys
        .filter((k) => new URL(k.url).pathname === bookPath && k.url !== request.url)
        .map((k) => cache.delete(k)));
    await cache.put(request, response);
    const opened = await markOpened(cache, bookPath);

    // Evict the least recently opened books beyond MAX_BOOKS, with their images.
    const books = (await cache.keys())
        .map((k) => new URL(k.url))
        .filter((u) => u.pathname.startsWith(`${ROOT}load_book/`));
    if (books.length <= MAX_BOOKS) return;
    books.sort((a, b) => (opened[a.pathname] || 0) - (opened[b.pathname] || 0));
    for (const u of books.slice(0, books.length - MAX_BOOKS)) {
        const filename = u.pathname.slice(`${ROOT}load_book/`.length);
        delete opened[u.pathname];
        await cache.delete(u.href);
        const related = (await cache.keys()).filter((k) =>
            new URL(k.url).pathname.startsWith(`${ROOT}book_asset/${filename}/`));
        await Promise.all(related.map((k) => cache.delete(k)));
    }
    await cache.put(OPENED_KEY, new Response(JSON.stringify(opened), {
        headers: {'Content-Type': 'application/json'},
    }));
}

// Comic pages: cache-first by versioned URL (?v= the file's size). The last
// MAX_ISSUES issues opened stay; older ones go, pages and all.
const ISSUES_KEY = `${ROOT}__issues.json`;

async function comicPage(request, url, path) {
    const cache = await caches.open(COMICS_CACHE);
    const cached = await cache.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok && url.searchParams.has('v')) {
        await cache.put(request, response.clone());
        await rememberIssue(cache, path.split('/')[2]);
    }
    return response;
}

async function rememberIssue(cache, issue) {
    const res = await cache.match(ISSUES_KEY);
    let opened = {};
    try { opened = res ? await res.json() : {}; } catch { opened = {}; }
    const fresh = !(issue in opened);
    opened[issue] = Date.now();
    if (fresh) {
        const ids = Object.keys(opened).sort((a, b) => opened[a] - opened[b]);
        const drop = ids.slice(0, Math.max(0, ids.length - MAX_ISSUES));
        if (drop.length) {
            const keys = await cache.keys();
            for (const id of drop) {
                delete opened[id];
                await Promise.all(keys.filter((k) => new URL(k.url).pathname.startsWith(`${ROOT}comics/issue/${id}/`)).map((k) => cache.delete(k)));
            }
        }
    }
    await cache.put(ISSUES_KEY, new Response(JSON.stringify(opened), {headers: {'Content-Type': 'application/json'}}));
}
