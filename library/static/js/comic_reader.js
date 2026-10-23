// The comic reader: one page, two pages side by side, or one long scroll.
// Tap or click the left/right third to turn (swapped right-to-left for
// manga), the middle to show or hide the bars. Keys: ←/→, space, Home/End,
// 1/2/3 for the layout, F for fit, R for right-to-left.
//
// Your page is kept on this device as well as sent, so reading offline (or
// through a failed save) never loses it, and once an issue is open its pages
// are fetched quietly so it reads offline too (sw.js keeps the last few).

(function () {
    const root = document.getElementById('reader');
    const stage = document.getElementById('stage');
    const slider = document.getElementById('pageSlider');
    const countEl = document.getElementById('pageCount');
    const total = Number(root.dataset.pages) || 0;
    const pageUrl = (n) => `${root.dataset.pageUrl}${n}?v=${root.dataset.version}`;
    const store = {
        get(key, fallback) { try { return localStorage.getItem(`comics.${key}`) ?? fallback; } catch (e) { return fallback; } },
        set(key, value) { try { localStorage.setItem(`comics.${key}`, value); } catch (e) { /* private mode */ } },
    };

    const POSITION_KEY = `comicPosition:${root.dataset.issueId}`;
    const readLocal = () => { try { return JSON.parse(localStorage.getItem(POSITION_KEY)); } catch (e) { return null; } };
    const writeLocal = (value) => { try { localStorage.setItem(POSITION_KEY, JSON.stringify(value)); } catch (e) { /* private mode */ } };
    const local = readLocal();
    // A page this device couldn't send yet wins over the server's.
    let page = Math.min((local && local.pending && !local.finished ? local.page : Number(root.dataset.page)) || 0, Math.max(total - 1, 0));
    let mode = store.get('mode', window.innerWidth > window.innerHeight * 1.2 ? 'double' : 'single');
    let fit = store.get('fit', 'height'); // height | width
    let rtl = store.get(`rtl.${root.dataset.issueId}`, store.get('rtl', '0')) === '1';
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

    function render() {
        root.dataset.mode = mode;
        root.dataset.fit = fit;
        root.classList.toggle('is-rtl', rtl);
        document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.mode === mode)));
        document.getElementById('rtlButton').setAttribute('aria-pressed', String(rtl));
        // Shows what a press does: fit to width while fitted to height, and back.
        const fitButton = document.getElementById('fitButton');
        const toWidth = fit === 'height';
        fitButton.innerHTML = icon(toWidth ? 'unfold-horizontal' : 'unfold-vertical');
        fitButton.title = `Fit to ${toWidth ? 'width' : 'height'} (F)`;
        fitButton.setAttribute('aria-label', `Fit to ${toWidth ? 'width' : 'height'}`);
        slider.style.direction = rtl ? 'rtl' : 'ltr';
        if (mode === 'scroll') return renderScroll();

        const pages = spreadAt(page);
        const imgs = pages.map(load);
        const order = rtl ? [...imgs].reverse() : imgs;
        const spread = document.createElement('div');
        spread.className = `cr-spread cr-spread--${imgs.length}`;
        order.forEach(img => spread.append(img));
        stage.replaceChildren(spread);
        stage.scrollTop = 0;
        stage.scrollLeft = 0;
        showCount(pages);
        // Once sizes are known a spread may change shape (a wide page).
        imgs.forEach(img => {
            if (!img.complete) img.addEventListener('load', () => { if (spreadAt(page).join() !== pages.join()) render(); }, {once: true});
        });
        // Load ahead.
        for (let i = 1; i <= 3; i++) load(pages[pages.length - 1] + i);
        load(pages[0] - 1);
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
        countEl.textContent = `${label} / ${total}`;
        slider.value = pages[0] + 1;
    }

    let saveTimer = null;
    function send(body) {
        return fetch(root.dataset.progressUrl, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), keepalive: true})
            .then((r) => {
                if (!r.ok) throw new Error(r.status);
                const now = readLocal();
                if (now && now.page === body.page && Boolean(now.finished) === Boolean(body.finished)) writeLocal({...now, pending: false});
            });
    }
    function saveProgress() {
        clearTimeout(saveTimer);
        const last = mode === 'scroll' ? page : spreadAt(page).slice(-1)[0];
        writeLocal({page: last, finished: false, pending: true});
        saveTimer = setTimeout(() => send({page: last}).catch(() => { /* kept here; sent when back online */ }), 600);
    }
    const resend = () => {
        const now = readLocal();
        if (now && now.pending) send(now.finished ? {page: now.page, finished: true} : {page: now.page}).catch(() => {});
    };
    window.addEventListener('online', resend);
    resend();

    function go(n) {
        if (mode === 'scroll') {
            const target = stage.querySelector(`[data-page="${n}"]`);
            if (target) target.scrollIntoView({behavior: 'smooth'});
            return;
        }
        if (n >= total) return finished();
        page = Math.max(0, Math.min(n, total - 1));
        render();
    }

    const next = () => {
        if (mode === 'scroll') return stage.scrollBy({top: stage.clientHeight * 0.9, behavior: 'smooth'});
        go(spreadAt(page).slice(-1)[0] + 1);
    };
    const prev = () => {
        if (mode === 'scroll') return stage.scrollBy({top: -stage.clientHeight * 0.9, behavior: 'smooth'});
        const first = spreadAt(page)[0];
        if (first > 0) go(spreadAt(first - 1)[0]);
    };

    function finished() {
        clearTimeout(saveTimer);
        writeLocal({page: total - 1, finished: true, pending: true});
        send({page: total - 1, finished: true}).catch(() => {});
        const end = document.createElement('div');
        end.className = 'cr-end';
        const nextUrl = root.dataset.nextUrl;
        end.innerHTML = `<p>The end.</p>`;
        if (nextUrl) {
            const a = document.createElement('a');
            a.className = 'cr-end__next';
            a.href = nextUrl;
            a.textContent = 'Next issue';
            end.append(a);
        }
        const back = document.createElement('button');
        back.type = 'button';
        back.textContent = 'Back to the last page';
        back.addEventListener('click', () => render());
        end.append(back);
        stage.replaceChildren(end);
        root.classList.remove('bars-hidden');
    }

    // Tap zones.
    stage.addEventListener('click', (e) => {
        if (e.target.closest('.cr-end')) return;
        if (mode === 'scroll') { root.classList.toggle('bars-hidden'); return; }
        const x = e.clientX / window.innerWidth;
        if (x > 0.35 && x < 0.65) { root.classList.toggle('bars-hidden'); return; }
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

    document.addEventListener('keydown', (e) => {
        if (e.target.matches('input, select, textarea') && e.target !== slider) return;
        const key = e.key;
        if (key === 'ArrowRight') { rtl ? prev() : next(); }
        else if (key === 'ArrowLeft') { rtl ? next() : prev(); }
        else if (key === ' ' || key === 'PageDown') { if (mode !== 'scroll' || key === 'PageDown') { e.preventDefault(); e.shiftKey ? prev() : next(); } }
        else if (key === 'PageUp') { e.preventDefault(); prev(); }
        else if (key === 'Home') go(0);
        else if (key === 'End') go(total - 1);
        else if (key === '1' || key === '2' || key === '3') setMode({1: 'single', 2: 'double', 3: 'scroll'}[key]);
        else if (key === 'f' || key === 'F') toggleFit();
        else if (key === 'r' || key === 'R') toggleRtl();
        else if (key === 'Escape') window.location = document.querySelector('.cr-bar a').href;
        else return;
    });

    function setMode(value) {
        mode = value;
        store.set('mode', mode);
        stage.replaceChildren();
        render();
    }
    function toggleFit() {
        fit = fit === 'height' ? 'width' : 'height';
        store.set('fit', fit);
        render();
    }
    function toggleRtl() {
        rtl = !rtl;
        store.set(`rtl.${root.dataset.issueId}`, rtl ? '1' : '0');
        store.set('rtl', rtl ? '1' : '0');
        render();
    }

    document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
    document.getElementById('fitButton').addEventListener('click', toggleFit);
    document.getElementById('rtlButton').addEventListener('click', toggleRtl);
    slider.addEventListener('input', () => go(Number(slider.value) - 1));

    if (!total) {
        stage.textContent = 'This file has no pages.';
        return;
    }
    render();
    stage.focus({preventScroll: true});
    // The whole issue, quietly, for reading offline.
    (window.requestIdleCallback || ((fn) => setTimeout(fn, 2000)))(async () => {
        if (!('caches' in window) || !navigator.serviceWorker || !navigator.serviceWorker.controller) return;
        for (let n = 0; n < total; n++) {
            try { await fetch(pageUrl(n)); } catch (e) { return; }
        }
        try { await (await caches.open('comics-v1')).put(appUrl(`/comics/issue/${root.dataset.issueId}/saved`), new Response('1')); } catch (e) { /* storage full */ }
    });
    // Bars fade out once you start reading.
    setTimeout(() => root.classList.add('bars-hidden'), 2500);
})();
