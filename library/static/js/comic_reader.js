// The comic reader: the book reader's frame (reader.css) around pages — one
// page, two side by side, or one long scroll. The bar stays hidden until you
// reach for it: tap the middle, or bring the pointer to the top edge. Tap or
// click the left/right third to turn (swapped right to left for manga).
// Everything else is in the Aa panel. `?` lists the keys.
//
// Your page is kept on this device as well as sent, so reading offline (or
// through a failed save) never loses it; a page the server hasn't confirmed
// is sent again when the connection comes back.

(function () {
    const root = document.getElementById('reader');
    const stage = document.getElementById('stage');
    const bar = document.getElementById('topBar');
    const panel = document.getElementById('reader-settings');
    const aa = document.getElementById('settings-toggle');
    const slider = document.getElementById('pageSlider');
    const sliderCount = document.getElementById('pageSliderCount');
    const footCount = document.getElementById('pageCount');
    const progressLine = document.getElementById('chapter-progress');
    const total = Number(root.dataset.pages) || 0;
    const issueId = root.dataset.issueId;
    const pageUrl = (n) => `${root.dataset.pageUrl}${n}?v=${root.dataset.version}`;
    const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const store = {
        get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch (e) { return fallback; } },
        set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
    };

    // --- Where you are: the server's word, unless this device has a newer
    // page it couldn't send yet. ---
    const POSITION_KEY = `comicPosition:${issueId}`;
    const readLocal = () => { try { return JSON.parse(store.get(POSITION_KEY, 'null')); } catch (e) { return null; } };
    const local = readLocal();
    let page = Number(root.dataset.page) || 0;
    if (local && local.pending && !local.finished) page = local.page;
    page = Math.min(page, Math.max(total - 1, 0));

    let mode = store.get('comics.mode', window.innerWidth > window.innerHeight * 1.2 ? 'double' : 'single');
    let fit = store.get('comics.fit', 'height'); // height | width
    let rtl = store.get(`comics.rtl.${issueId}`, store.get('comics.rtl', '0')) === '1';
    const sizes = {}; // page -> {w, h}, learned as pages load
    const cache = new Map();

    function load(n) {
        if (n < 0 || n >= total) return null;
        if (!cache.has(n)) {
            const img = new Image();
            img.decoding = 'async';
            img.alt = `Page ${n + 1}`;
            img.src = pageUrl(n);
            img.addEventListener('load', () => { sizes[n] = {w: img.naturalWidth, h: img.naturalHeight}; }, {once: true});
            cache.set(n, img);
            // Keep memory bounded on phones.
            if (cache.size > 12) {
                for (const key of cache.keys()) {
                    if (Math.abs(key - n) > 6) { cache.delete(key); break; }
                }
            }
        }
        return cache.get(n);
    }

    const isWide = (n) => sizes[n] && sizes[n].w > sizes[n].h;

    // Which pages show together in two-page mode: the cover alone, then
    // pairs, except that a wide page (a spread) is alone.
    function spreadAt(n) {
        if (mode !== 'double' || n === 0 || isWide(n)) return [n];
        const start = n % 2 === 1 ? n : n - 1;
        if (start !== n && (start === 0 || isWide(start))) return [n];
        const pair = [start, start + 1].filter(p => p < total && !isWide(p));
        return pair.length === 2 ? pair : [n];
    }

    // --- Drawing ---
    let turning = 0;  // +1 onwards, -1 back, 0 a jump
    let waitTimer = null;

    function render() {
        root.dataset.mode = mode;
        root.dataset.fit = fit;
        root.classList.toggle('is-rtl', rtl);
        slider.style.direction = rtl ? 'rtl' : 'ltr';
        syncPanel();
        if (mode === 'scroll') return renderScroll();

        const pages = spreadAt(page);
        const imgs = pages.map(load);
        const order = rtl ? [...imgs].reverse() : imgs;
        const spread = document.createElement('div');
        spread.className = `cr-spread cr-spread--${imgs.length}`;
        if (turning && !REDUCED) spread.classList.add('is-turning', ((turning > 0) !== rtl) ? 'is-turning-fwd' : 'is-turning-back');
        turning = 0;
        order.forEach(img => spread.append(img));
        // A page still on its way says which it is, after a moment.
        const wait = document.createElement('p');
        wait.className = 'cr-wait';
        wait.hidden = true;
        wait.textContent = `Page ${pages[0] + 1}`;
        stage.replaceChildren(spread, wait);
        stage.scrollTop = 0;
        stage.scrollLeft = 0;
        clearTimeout(waitTimer);
        if (imgs.some(img => !img.complete)) {
            waitTimer = setTimeout(() => { if (imgs.some(img => !img.complete)) wait.hidden = false; }, 300);
            imgs.forEach(img => img.addEventListener('load', () => { if (imgs.every(i => i.complete)) wait.remove(); }, {once: true}));
        }
        showCount(pages);
        // Once sizes are known a spread may change shape (a wide page).
        imgs.forEach(img => {
            if (!img.complete) img.addEventListener('load', () => { if (spreadAt(page).join() !== pages.join()) render(); }, {once: true});
        });
        // Load ahead; near the end, the next issue's first page too.
        for (let i = 1; i <= 3; i++) load(pages[pages.length - 1] + i);
        load(pages[0] - 1);
        if (root.dataset.nextFirstPage && pages[pages.length - 1] >= total - 3) new Image().src = root.dataset.nextFirstPage;
        saveProgress();
    }

    function renderScroll() {
        if (stage.querySelector('.cr-scroll')) return;
        const column = document.createElement('div');
        column.className = 'cr-scroll';
        for (let n = 0; n < total; n++) {
            const img = document.createElement('img');
            img.loading = 'lazy';
            img.alt = `Page ${n + 1}`;
            img.dataset.page = n;
            img.src = pageUrl(n);
            column.append(img);
        }
        stage.replaceChildren(column);
        const observer = new IntersectionObserver((entries) => {
            for (const entry of entries) {
                if (entry.isIntersecting) {
                    page = Number(entry.target.dataset.page);
                    showCount([page]);
                    saveProgress();
                }
            }
        }, {root: stage, rootMargin: '-45% 0px -45% 0px'});
        column.querySelectorAll('img').forEach(img => observer.observe(img));
        const target = column.children[page];
        if (target) requestAnimationFrame(() => target.scrollIntoView());
    }

    function showCount(pages) {
        const label = pages.length > 1 ? `${pages[0] + 1}–${pages[1] + 1}` : `${pages[0] + 1}`;
        footCount.textContent = `${label} / ${total}`;
        sliderCount.textContent = `${label} of ${total}`;
        slider.value = pages[0] + 1;
        progressLine.style.width = `${total ? (100 * (pages[pages.length - 1] + 1) / total) : 0}%`;
    }

    // --- Saving your page: here first, then the server. ---
    let saveTimer = null;
    function writeLocal(value) { store.set(POSITION_KEY, JSON.stringify(value)); }

    function send(body) {
        return fetch(root.dataset.progressUrl, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), keepalive: true})
            .then(r => {
                if (!r.ok) throw new Error(r.status);
                const now = readLocal();
                if (now && now.page === body.page && Boolean(now.finished) === Boolean(body.finished)) writeLocal({...now, pending: false});
            });
    }

    function saveProgress(finished = false) {
        clearTimeout(saveTimer);
        const last = finished ? total - 1 : (mode === 'scroll' ? page : spreadAt(page).slice(-1)[0]);
        const body = finished ? {page: last, finished: true} : {page: last};
        writeLocal({page: last, finished, pending: true});
        saveTimer = setTimeout(() => send(body).catch(() => { /* kept here; sent again when online */ }), finished ? 0 : 600);
    }

    window.addEventListener('online', () => {
        const now = readLocal();
        if (now && now.pending) send(now.finished ? {page: now.page, finished: true} : {page: now.page}).catch(() => {});
    });
    if (local && local.pending) send(local.finished ? {page: local.page, finished: true} : {page: local.page}).catch(() => {});

    // --- Turning ---
    function go(n) {
        if (mode === 'scroll') {
            const target = stage.querySelector(`[data-page="${n}"]`);
            if (target) target.scrollIntoView({behavior: REDUCED ? 'auto' : 'smooth'});
            return;
        }
        if (n >= total) return finished();
        page = Math.max(0, Math.min(n, total - 1));
        render();
    }

    const next = () => {
        if (mode === 'scroll') return stage.scrollBy({top: stage.clientHeight * 0.9, behavior: 'smooth'});
        turning = 1;
        go(spreadAt(page).slice(-1)[0] + 1);
    };
    const prev = () => {
        if (mode === 'scroll') return stage.scrollBy({top: -stage.clientHeight * 0.9, behavior: 'smooth'});
        const first = spreadAt(page)[0];
        turning = -1;
        if (first > 0) go(spreadAt(first - 1)[0]);
    };

    // The end: marked read, and on to the next issue as the book reader goes
    // on to the next chapter.
    function finished() {
        saveProgress(true);
        const end = document.createElement('div');
        end.className = 'cr-end';
        const nextUrl = root.dataset.nextUrl;
        if (nextUrl) {
            const nav = document.createElement('nav');
            nav.className = 'chapter-end';
            nav.setAttribute('aria-label', 'Next issue');
            const a = document.createElement('a');
            a.href = nextUrl;
            a.innerHTML = '<span class="chapter-end__label">Next</span><span class="chapter-end__title"></span><span aria-hidden="true">→</span>';
            a.querySelector('.chapter-end__title').textContent = root.dataset.nextLabel;
            nav.append(a);
            end.append(nav);
        } else {
            const done = document.createElement('p');
            done.className = 'cr-end__done';
            done.textContent = `That’s the last issue here. Marked as read.`;
            const nav = document.createElement('nav');
            nav.className = 'chapter-end';
            const a = document.createElement('a');
            a.href = root.dataset.seriesUrl;
            a.innerHTML = '<span class="chapter-end__label">Back to</span><span class="chapter-end__title"></span><span aria-hidden="true">→</span>';
            a.querySelector('.chapter-end__title').textContent = root.dataset.seriesName;
            nav.append(a);
            end.append(done, nav);
        }
        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'cr-end__back';
        back.textContent = 'Back to the last page';
        back.addEventListener('click', () => render());
        end.append(back);
        stage.replaceChildren(end);
        progressLine.style.width = '100%';
        footCount.textContent = '';
        showBar(true);
    }

    // --- The bar: hidden until wanted, as in the book reader ---
    function showBar(show) {
        if (!show && bar.classList.contains('pinned')) return;  // the Aa panel is open
        bar.classList.toggle('visible', show);
        document.documentElement.classList.toggle('bar-visible', show);
    }
    const barShown = () => bar.classList.contains('visible');

    if (window.matchMedia('(hover: hover)').matches) {
        let lastY = null;
        document.addEventListener('mousemove', (e) => {
            if (e.clientY === lastY) return;
            const first = lastY === null;
            lastY = e.clientY;
            if (first) return;
            if (e.clientY < 28) showBar(true);
            else if (e.clientY > bar.offsetHeight + 60 && !bar.contains(e.target)) showBar(false);
        }, {passive: true});
    }

    // Tap zones: the sides turn, the middle shows or hides the bar.
    stage.addEventListener('click', (e) => {
        if (e.target.closest('.cr-end')) return;
        if (!panel.hidden) return openPanel(false);
        if (mode === 'scroll') return showBar(!barShown());
        const x = e.clientX / window.innerWidth;
        if (x > 0.35 && x < 0.65) return showBar(!barShown());
        const forward = (x >= 0.65) !== rtl;
        forward ? next() : prev();
    });

    // Swipes (when the page isn't zoomed in).
    let touch = null;
    stage.addEventListener('touchstart', (e) => {
        if (e.touches.length === 1) touch = {x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now()};
    }, {passive: true});
    stage.addEventListener('touchend', (e) => {
        if (!touch || mode === 'scroll' || (window.visualViewport && window.visualViewport.scale > 1.05)) { touch = null; return; }
        const dx = e.changedTouches[0].clientX - touch.x;
        const dy = e.changedTouches[0].clientY - touch.y;
        if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5 && Date.now() - touch.t < 600) {
            const forward = (dx < 0) !== rtl;
            forward ? next() : prev();
            e.preventDefault();
        }
        touch = null;
    });

    // --- The Aa panel ---
    function currentTheme() {
        const dark = document.documentElement.classList.contains('dark-mode');
        const t = store.get('readerTheme', dark ? 'night' : 'day');
        if (dark && (t === 'day' || t === 'sepia')) return 'night';
        if (!dark && (t === 'night' || t === 'black')) return 'day';
        return t;
    }
    function setTheme(theme) {
        const html = document.documentElement;
        const dark = theme === 'night' || theme === 'black';
        html.classList.toggle('dark-mode', dark);
        html.classList.toggle('theme-sepia', theme === 'sepia');
        html.classList.toggle('theme-black', theme === 'black');
        store.set('darkMode', dark ? 'enabled' : 'disabled');
        store.set('readerTheme', theme);
        syncPanel();
    }
    const toggleNight = () => setTheme(['night', 'black'].includes(currentTheme()) ? 'day' : 'night');

    function syncPanel() {
        const values = {mode, fit, direction: rtl ? 'rtl' : 'ltr', theme: currentTheme()};
        panel.querySelectorAll('.rs-seg').forEach(seg => seg.querySelectorAll('button').forEach(b =>
            b.setAttribute('aria-pressed', String(b.dataset.value === values[seg.dataset.setting]))));
    }

    function openPanel(open) {
        panel.hidden = !open;
        aa.setAttribute('aria-expanded', String(open));
        bar.classList.toggle('pinned', open);
        if (open) { syncPanel(); showBar(true); }
    }
    aa.addEventListener('click', (e) => { e.stopPropagation(); openPanel(panel.hidden); });
    document.addEventListener('pointerdown', (e) => {
        if (!panel.hidden && !panel.contains(e.target) && !aa.contains(e.target)) openPanel(false);
    });
    panel.addEventListener('click', (e) => {
        const b = e.target.closest('.rs-seg button');
        if (!b) return;
        const setting = b.closest('.rs-seg').dataset.setting;
        const v = b.dataset.value;
        if (setting === 'mode') setMode(v);
        else if (setting === 'fit') setFit(v);
        else if (setting === 'direction') setRtl(v === 'rtl');
        else if (setting === 'theme') setTheme(v);
    });
    slider.addEventListener('input', () => go(Number(slider.value) - 1));

    function setMode(value) {
        if (value === mode) return;
        mode = value;
        store.set('comics.mode', mode);
        stage.replaceChildren();
        render();
    }
    function setFit(value) {
        fit = value;
        store.set('comics.fit', fit);
        render();
    }
    function setRtl(value) {
        rtl = value;
        store.set(`comics.rtl.${issueId}`, rtl ? '1' : '0');
        store.set('comics.rtl', rtl ? '1' : '0');
        render();
    }

    // --- Keys, and the ? sheet (the book reader's) ---
    const SHORTCUTS = [
        ['← →', 'Previous / next page'],
        ['Space', 'Next page'],
        ['Home End', 'First / last page'],
        ['1 2 3', 'One page, two pages, scroll'],
        ['F', 'Fit height or width'],
        ['R', 'Right to left (manga)'],
        ['N', 'Night mode'],
        ['Esc', 'Close, or show and hide the bar'],
        ['?', 'Show these shortcuts'],
    ];
    function toggleHelp() {
        const open = document.querySelector('.shortcut-help');
        if (open) return open.remove();
        const sheet = document.createElement('div');
        sheet.className = 'shortcut-help';
        sheet.setAttribute('role', 'dialog');
        sheet.setAttribute('aria-label', 'Keyboard shortcuts');
        const list = document.createElement('dl');
        for (const [keys, what] of SHORTCUTS) {
            const dt = document.createElement('dt');
            keys.split(' ').forEach((k, i) => {
                if (i) dt.append(' ');
                const kbd = document.createElement('kbd');
                kbd.textContent = k;
                dt.append(kbd);
            });
            const dd = document.createElement('dd');
            dd.textContent = what;
            list.append(dt, dd);
        }
        sheet.append(list);
        sheet.addEventListener('click', () => sheet.remove());
        document.body.append(sheet);
    }

    document.addEventListener('keydown', (e) => {
        if (e.target.matches('input, select, textarea') && e.target !== slider) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        const key = e.key;
        if (key === 'Escape') {
            // Esc closes what's open, else shows or hides the bar; it never leaves.
            if (document.querySelector('.shortcut-help')) document.querySelector('.shortcut-help').remove();
            else if (!panel.hidden) openPanel(false);
            else showBar(!barShown());
            return;
        }
        if (key === 'ArrowRight') { rtl ? prev() : next(); }
        else if (key === 'ArrowLeft') { rtl ? next() : prev(); }
        else if (key === ' ' || key === 'PageDown') { if (mode !== 'scroll' || key === 'PageDown') { e.preventDefault(); e.shiftKey ? prev() : next(); } }
        else if (key === 'PageUp') { e.preventDefault(); prev(); }
        else if (key === 'Home') go(0);
        else if (key === 'End') go(total - 1);
        else if (key === '1' || key === '2' || key === '3') setMode({1: 'single', 2: 'double', 3: 'scroll'}[key]);
        else if (key === 'f' || key === 'F') setFit(fit === 'height' ? 'width' : 'height');
        else if (key === 'r' || key === 'R') setRtl(!rtl);
        else if (key === 'n' || key === 'N') toggleNight();
        else if (key === '?') toggleHelp();
        else return;
    });

    // --- Offline: the whole issue, quietly, once it's open (sw.js keeps the
    // last few issues opened, as it does books). ---
    async function keepForOffline() {
        if (!('caches' in window) || !navigator.serviceWorker?.controller) return;
        for (let n = 0; n < total; n++) {
            try { await fetch(pageUrl(n), {credentials: 'same-origin'}); } catch (e) { return; }
        }
        try {
            const cache = await caches.open('comics-v1');
            await cache.put(appUrl(`/comics/issue/${issueId}/saved`), new Response('1'));
        } catch (e) { /* storage full */ }
    }

    if (!total) {
        stage.innerHTML = '<p class="cr-opening">This file is empty or damaged.</p>';
        return;
    }
    render();
    stage.focus({preventScroll: true});
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 2000));
    idle(() => keepForOffline());
})();
