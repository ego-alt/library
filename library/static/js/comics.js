// Comics pages: one small module per page, picked by <body data-page>.

const comicsApi = (path, options) => apiFetch(`/comics/api${path}`, options);


// --- The wall of series: one search box and All / Unread / Reading / Finished,
// like the books (main.js), filtered here since every series is on the page.
// The server orders it: what you're partway through first, then A–Z. ---

const SERIES_EMPTY = {
    unread: ['Nothing unread', 'You’ve opened every series here.'],
    reading: ['Nothing on the go', 'Series you start reading will appear here.'],
    finished: ['Nothing finished yet', 'Series you’ve read every issue of will appear here.'],
};

function initSeries() {
    const grid = document.getElementById('library');
    const search = document.getElementById('librarySearch');
    bindSearchBox(search);
    if (!grid) return;
    const empty = document.getElementById('emptyState');
    const filter = document.querySelector('.status-filter[aria-label="Reading status"]');
    const cards = [...grid.children];
    let view = filter.querySelector('[aria-checked="true"]').dataset.view;

    function apply() {
        const q = search.value.trim().toLowerCase();
        search.closest('.library-toolbar')?.classList.toggle('is-searching', Boolean(q));
        let shown = 0;
        for (const card of cards) {
            card.hidden = q ? !card.dataset.name.includes(q) : (view !== 'all' && card.dataset.state !== view);
            if (!card.hidden) shown += 1;
        }
        empty.hidden = shown > 0;
        if (!shown) {
            const [title, body] = q ? [`Nothing matches “${search.value.trim()}”`, 'Try a different word, or clear the search.'] : SERIES_EMPTY[view];
            empty.querySelector('h3').textContent = title;
            empty.querySelector('p').textContent = body;
        }
    }

    filter.addEventListener('click', (e) => {
        const button = e.target.closest('[data-view]');
        if (!button) return;
        if (search.value) {   // a tab clears the search, which looks through everything
            search.value = '';
            search.dispatchEvent(new Event('input'));
        }
        else if (button.dataset.view === view) return;
        view = button.dataset.view;
        setRadio(filter, button);
        rememberShelfView('comics', view);
        apply();
    });
    search.addEventListener('input', apply);
    apply();
}

// --- One series: its issues as covers, each with a menu (mark read,
// download; for admins also replace or delete the file, or add one to a
// missing issue, and once a downloader is set up find, choose a release,
// want or skip). Admins see the missing ones, greyed out. ---

const MISSING_STATE = {wanted: 'Wanted', snatched: 'Downloading', skipped: 'Not wanted'};
const MONITOR_LABELS = [['future', 'New issues as they come out', 'new issues'], ['all', 'Every missing issue', 'every missing issue'], ['none', 'Only the ones I choose', 'only the issues you choose']];

// Mark an issue read (its last page) or unread (back to the start).
async function setRead(issue, read) {
    return comicsApi(`/issues/${issue.id}/progress`, {method: 'PUT', body: read ? {page: Math.max(0, (issue.pages || 1) - 1), finished: true} : {page: 0, finished: false}});
}

function initSeriesDetail() {
    const head = document.querySelector('.series-head');
    const seriesId = head.dataset.seriesId;
    const wall = document.getElementById('issueWall');
    const issues = new Map(JSON.parse(document.getElementById('issuesData').textContent).map(i => [String(i.id), i]));
    const card = id => wall && wall.querySelector(`[data-issue-id="${id}"]`);

    // A just-followed series fills in as soon as the worker has its issues.
    if (document.getElementById('seriesPending')) {
        const poll = async () => {
            try {
                const state = await comicsApi(`/series/${seriesId}`);
                if (!state.pending) return window.location.reload();
            } catch (e) { /* try again */ }
            setTimeout(poll, 3000);
        };
        setTimeout(poll, 3000);
    }

    function caption(issue) {
        const el = card(issue.id);
        if (!el) return;
        let meta = el.querySelector('.book-caption__author');
        if (!meta) el.querySelector('.book-caption').append(meta = h('span', {class: 'book-caption__author'}));
        let state = '';
        if (issue.has_file) state = issue.finished ? 'Read' : (issue.page && issue.pages ? `${Math.floor(100 * (issue.page + 1) / issue.pages)}%` : '');
        else if (issue.released && (issue.status !== 'skipped' || head.dataset.downloads === '1')) state = MISSING_STATE[issue.status] || '';
        meta.textContent = issue.released || issue.has_file ? state : `Out ${formatDate(issue.date)}`;
    }

    function showRead(issue) {
        card(issue.id)?.classList.toggle('is-read', issue.finished);
        caption(issue);
    }

    // Flips at once; put back if the server says no.
    async function toggleRead(issue) {
        const before = {page: issue.page, finished: issue.finished};
        Object.assign(issue, {finished: !issue.finished, page: issue.finished ? 0 : Math.max(0, (issue.pages || 1) - 1)});
        showRead(issue);
        try {
            const data = await setRead(issue, issue.finished);
            Object.assign(issue, {page: data.page, finished: data.finished});
        } catch (e) {
            Object.assign(issue, before);
            showRead(issue);
            showToast(e.message, 'error');
        }
    }

    // A missing issue's caption and fade follow its status.
    function showStatus(issue) {
        const el = card(issue.id);
        if (!el || issue.has_file) return;
        el.className = el.className.replace(/\bstatus-\S+/g, '').trim() + ` status-${issue.status}`;
        caption(issue);
    }

    // The description folds to two lines; More shows the rest.
    const desc = document.getElementById('seriesDesc');
    const descMore = document.getElementById('descMore');
    if (desc && descMore) {
        desc.classList.add('is-folded');
        descMore.hidden = desc.scrollHeight <= desc.clientHeight + 2;
        descMore.addEventListener('click', () => { desc.classList.remove('is-folded'); descMore.remove(); });
    }

    // Phones have no ⋯ on the covers: press and hold one for its menu, as a
    // book on the shelf opens its details.
    let pressed = false;
    if (wall) (() => {
        let timer = null, start = null;
        wall.addEventListener('touchstart', (e) => {
            const book = e.target.closest('.book');
            if (!book || e.touches.length !== 1) return;
            pressed = false;
            start = {x: e.touches[0].clientX, y: e.touches[0].clientY};
            timer = setTimeout(() => {
                const issue = issues.get(book.closest('[data-issue-id]').dataset.issueId);
                const items = menuItems(issue, book);
                if (!items.filter(Boolean).length) return;
                pressed = true;
                navigator.vibrate?.(10);
                openMenu(book, items);
            }, 500);
        }, {passive: true});
        const cancel = () => { clearTimeout(timer); timer = null; };
        wall.addEventListener('touchmove', (e) => {
            if (timer && (Math.abs(e.touches[0].clientX - start.x) > 10 || Math.abs(e.touches[0].clientY - start.y) > 10)) cancel();
        }, {passive: true});
        wall.addEventListener('touchend', cancel, {passive: true});
        wall.addEventListener('contextmenu', (e) => { if (e.target.closest('.book') && matchMedia('(hover: none)').matches) e.preventDefault(); });
    })();

    if (wall) wall.addEventListener('click', (e) => {
        if (pressed) { e.preventDefault(); pressed = false; return; }
        const el = e.target.closest('[data-issue-id]');
        if (!el) return;
        const issue = issues.get(el.dataset.issueId);
        const button = e.target.closest('[data-action="menu"]');
        if (button) {
            openMenu(button, menuItems(issue, button));
        } else if (!issue.has_file && e.target.closest('.book > a')) {
            e.preventDefault();
            if (window.isAdmin) openMenu(e.target.closest('.book > a'), menuItems(issue, e.target.closest('.book > a')));
        }
    });

    function readerItems(issue) {
        if (!issue.has_file) return [];
        return [
            {label: issue.finished ? 'Mark as unread' : 'Mark as read', onClick: () => toggleRead(issue)},
            {label: 'Download', href: appUrl(`/comics/issue/${issue.id}/download`)},
        ];
    }

    let menuItems = readerItems;
    if (!window.isAdmin) return;

    // --- Admins ---
    const downloads = head.dataset.downloads === '1';
    const upload = document.getElementById('issueUpload');
    let uploadFor = null;

    // An issue you have: reading things, then a rule, then the file. One
    // you don't: getting it.
    menuItems = (issue, anchor) => {
        if (issue.has_file) return [
            ...readerItems(issue),
            {divider: true},
            {label: 'Replace the file…', onClick: () => { uploadFor = issue; upload.click(); }},
            {label: 'Delete the file…', danger: true, onClick: () => confirmMenu(anchor, `Delete the file for #${issue.number}? This can’t be undone.`, [{label: 'Keep it'}, {label: 'Delete the file', danger: true, onClick: () => deleteFile(issue)}])},
        ];
        // Finding, choosing a release and wanting only mean something once
        // a downloader is set up; without one, a missing issue is a file to add.
        const findable = downloads && issue.released && issue.status !== 'snatched';
        return [
            findable ? {label: 'Find now', onClick: () => findNow(issue)} : null,
            findable && window.pickRelease ? {label: 'Choose a release…', onClick: () => pickRelease({kind: 'comic', id: issue.id, label: `${issue.series} #${issue.number}`, onGrab: () => { issue.status = 'snatched'; showStatus(issue); }})} : null,
            downloads && issue.status !== 'snatched' ? {label: issue.status === 'wanted' ? 'Don’t want' : 'Want', onClick: () => setStatus(issue, issue.status === 'wanted' ? 'skipped' : 'wanted')} : null,
            {label: 'Add a file…', onClick: () => { uploadFor = issue; upload.click(); }},
        ];
    };

    async function setStatus(issue, status) {
        try {
            Object.assign(issue, await comicsApi(`/issues/${issue.id}`, {method: 'PATCH', body: {status}}));
            showStatus(issue);
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function findNow(issue) {
        showToast(`Looking for #${issue.number}…`);
        try {
            const data = await apiFetch(`/api/wanted/comic/${issue.id}/search`, {method: 'POST'});
            if (data.found === false) return showToast(data.message);
            issue.status = data.status;
            showStatus(issue);
            showToast(`Downloading #${issue.number}`);
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function deleteFile(issue) {
        try {
            Object.assign(issue, await comicsApi(`/issues/${issue.id}/file`, {method: 'DELETE'}));
            const el = card(issue.id);
            el.classList.remove('is-read', 'is-next');
            el.classList.add('is-missing', `status-${issue.status}`);
            el.dataset.have = '0';
            el.querySelector('.book > a').setAttribute('href', '#');
            el.querySelector('img')?.remove();
            caption(issue);
            showToast(`Deleted the file for #${issue.number}`);
        } catch (e) { showToast(e.message, 'error'); }
    }

    upload.addEventListener('change', async () => {
        const file = upload.files[0];
        if (!file || !uploadFor) return;
        const form = new FormData();
        form.append('file', file);
        showToast(`Adding ${file.name}…`);
        try {
            await comicsApi(`/issues/${uploadFor.id}/upload`, {method: 'POST', form});
            window.location.reload();
        } catch (e) { showToast(e.message, 'error'); }
        upload.value = '';
    });

    // "12 of 16 here": tap to show only those, again for all.
    const haveToggle = document.getElementById('haveToggle');
    if (haveToggle) haveToggle.addEventListener('click', () => {
        const only = haveToggle.getAttribute('aria-pressed') !== 'true';
        haveToggle.setAttribute('aria-pressed', String(only));
        haveToggle.title = only ? 'Show every issue' : 'Show only the issues here';
        wall.querySelectorAll('[data-issue-id]').forEach(el => { el.hidden = only && el.dataset.have !== '1'; });
    });

    async function setMonitor(value) {
        try {
            const data = await comicsApi(`/series/${seriesId}`, {method: 'PATCH', body: {monitor: value}});
            head.dataset.monitor = data.monitor;
            const getting = head.querySelector('.series-head__getting');
            if (getting) getting.firstChild.textContent = `Getting ${MONITOR_LABELS.find(([v]) => v === data.monitor)[2]} · `;
            // Every missing issue's status may have changed; read them again.
            const page = await fetch(location.href).then(r => r.text());
            const fresh = JSON.parse(new DOMParser().parseFromString(page, 'text/html').getElementById('issuesData').textContent);
            fresh.forEach(f => { const issue = issues.get(String(f.id)); if (issue) { Object.assign(issue, f); showStatus(issue); } });
            showToast(value === 'none' ? 'Only getting the issues you choose' : `Getting ${value === 'all' ? 'every missing issue' : 'new issues as they come out'}${data.wanted ? ` · ${data.wanted} wanted` : ''}`);
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function refresh() {
        try {
            const data = await comicsApi(`/series/${seriesId}/refresh`, {method: 'POST'});
            if (data.added) window.location.reload();
            else showToast('Up to date');
        } catch (err) { showToast(err.message, 'error'); }
    }

    document.addEventListener('click', (e) => {
        const button = e.target.closest('[data-action="monitor-menu"], [data-action="refresh"]');
        if (!button) return;
        if (button.dataset.action === 'refresh') return refresh();
        openMenu(button, MONITOR_LABELS.map(([value, label]) => ({label, checked: head.dataset.monitor === value, onClick: () => setMonitor(value)})));
    });
}

const PAGES = {series: initSeries, 'series-detail': initSeriesDetail};
document.addEventListener('DOMContentLoaded', () => {
    const init = PAGES[document.body.dataset.page];
    if (init) init();
});
