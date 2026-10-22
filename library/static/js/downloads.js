// Get and Downloads: asking for books and comics, and following everything
// on its way into the library. Also the release chooser the comics series
// page uses. Helpers are in ui.js.
(() => {

// --- Choosing a release by hand, for a book request or a comic issue ----------

let picker = null;

function pickerOverlay() {
    if (picker) return picker;
    picker = h('div', {class: 'metadata-overlay', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'releasesTitle'},
        h('div', {class: 'metadata-content releases-panel'},
            h('button', {class: 'close-metadata btn btn-ghost', 'aria-label': 'Close', dataset: {close: ''}}, '×'),
            h('h3', {id: 'releasesTitle'}, 'Releases'),
            h('p', {class: 'comics-hint', id: 'releasesStatus'}),
            h('ol', {class: 'release-list', id: 'releaseList'})));
    picker.addEventListener('click', (e) => { if (e.target === picker || e.target.closest('[data-close]')) picker.style.display = 'none'; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && picker) picker.style.display = 'none'; });
    document.body.append(picker);
    return picker;
}

/** Every release the indexers have for a wanted item, with why the ones
 * that don't match don't; Download sends one to the download client. */
async function pickRelease({kind, id, label, onGrab}) {
    const overlay = pickerOverlay();
    const list = overlay.querySelector('#releaseList');
    const status = overlay.querySelector('#releasesStatus');
    overlay.querySelector('#releasesTitle').textContent = label;
    status.textContent = 'Searching…';
    list.replaceChildren();
    overlay.style.display = 'flex';
    try {
        const data = await apiFetch(`/api/wanted/${kind}/${id}/releases`);
        const fits = data.releases.filter(r => r.score >= 0).length;
        status.textContent = (data.releases.length ? `${fits} of ${data.releases.length} match` : 'Nothing found yet') + (data.errors.length ? `. ${data.errors.join(' ')}` : '');
        list.append(...data.releases.map((r, index) => h('li', {class: r.score >= 0 ? 'release' : 'release is-rejected'},
            h('div', {class: 'release__text'},
                h('strong', {}, r.title),
                h('span', {}, [r.indexer, r.protocol === 'torrent' ? `${r.seeders ?? '?'} seeders` : null, formatSize(r.size), r.published, r.note].filter(Boolean).join(' · '))),
            h('button', {type: 'button', class: r.score >= 0 ? 'btn btn-primary' : 'btn btn-secondary', onclick: (e) => grab(e.currentTarget, index, data.token)}, 'Download'))));
    } catch (e) {
        status.textContent = e.message;
    }

    async function grab(button, index, token) {
        button.textContent = 'Sending…';
        await busy(button, async () => {
            try {
                const data = await apiFetch(`/api/wanted/${kind}/${id}/grab`, {method: 'POST', body: {token, index}});
                overlay.style.display = 'none';
                showToast(`Downloading ${label}`, 'success');
                if (onGrab) onGrab(data);
            } catch (e) { showToast(e.message, 'error'); }
        });
    }
}

window.pickRelease = pickRelease;

// "/" puts you in the search box, as on the books shelf.
function bindSearchKey(input) {
    document.addEventListener('keydown', (e) => {
        if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
        e.preventDefault();
        input.focus();
    });
}

// --- Get: one search for books and comics -----------------------------------
// Results are covers like the shelves: what each is to you (in the library,
// asked for, following) is in its caption, and the cover is the action.

const BOOK_STATE = {have: 'In your library', downloaded: 'In your library', wanted: 'Asked for', snatched: 'Downloading'};
const PHONE = window.matchMedia('(max-width: 640px)');
const PHONE_SHOWS = 6;

function initGet() {
    const form = document.getElementById('getForm');
    const input = document.getElementById('getQuery');
    const sections = {books: document.getElementById('bookResults'), comics: document.getElementById('comicResults')};
    const show = form.querySelector('[aria-label="Show"]');
    let shown = 'all';
    let generation = 0;
    bindSearchKey(input);

    function setShown(value) {
        shown = value;
        setRadio(show, show.querySelector(`[data-show="${value}"]`));
        applyShow();
    }

    // Under All on a phone, the first few of each, so comics aren't ten
    // screens down; the section's name (or "All 20 books") shows the rest.
    function applyShow() {
        for (const [kind, section] of Object.entries(sections)) {
            const results = section.querySelector('.get-results');
            const cards = [...results.children];
            section.hidden = (shown !== 'all' && shown !== kind) || !(cards.length || section.querySelector('.get-note').textContent);
            const cap = shown === 'all' && PHONE.matches && !results.dataset.loading;
            cards.forEach((card, i) => { card.hidden = cap && i >= PHONE_SHOWS; });
            const more = section.querySelector('.get-all');
            more.hidden = !(cap && cards.length > PHONE_SHOWS);
            more.textContent = `All ${cards.length} ${kind}`;
        }
    }

    function skeletons(n) {
        return Array.from({length: n}, () => h('div', {class: 'col-md-3 mb-3 book-skeleton-wrapper', 'aria-hidden': 'true'}, h('div', {class: 'book-skeleton'})));
    }

    function setCaption(card, parts) {
        const line = parts.filter(Boolean).join(' · ');
        let el = card.querySelector('.book-caption__author');
        if (!el) card.querySelector('.book-caption').append(el = h('span', {class: 'book-caption__author'}));
        el.textContent = line;
    }

    function bookCard(book) {
        const owned = book.status === 'have' || book.status === 'downloaded';
        const asked = BOOK_STATE[book.status] && !owned;
        const card = coverCard({
            href: owned && book.href ? book.href : '#',
            label: owned ? `Read ${book.title}` : (asked ? `${book.title}, ${BOOK_STATE[book.status].toLowerCase()}` : `Ask for ${book.title}`),
            title: book.title,
            meta: [book.author, BOOK_STATE[book.status] || book.year],
            cover: book.cover_url,
            imgAttrs: {referrerpolicy: 'no-referrer'},
        });
        if (owned && book.href) return card;
        card.querySelector('.book > a').addEventListener('click', async (e) => {
            e.preventDefault();
            if (BOOK_STATE[book.status] || card.classList.contains('is-busy')) return;
            card.classList.add('is-busy');
            try {
                const data = await apiFetch('/api/get/books', {method: 'POST', body: book});
                book.status = data.status;
                book.request_id = data.id;
                setCaption(card, [book.author, BOOK_STATE[data.status] || 'Asked for']);
                showToast(`Asked for ${book.title}`, 'success', data.created ? {label: 'Undo', onClick: () => undoAsk(book, card)} : null);
            } catch (err) {
                showToast(err.message, 'error');
            }
            card.classList.remove('is-busy');
        });
        return card;
    }

    async function undoAsk(book, card) {
        try {
            await apiFetch(`/api/book-requests/${book.request_id}`, {method: 'DELETE'});
            book.status = null;
            setCaption(card, [book.author, book.year]);
        } catch (err) { showToast(err.message, 'error'); }
    }

    function comicCard(row) {
        const followed = Boolean(row.followed_id);
        const card = coverCard({
            href: followed ? appUrl(`/comics/series/${row.followed_id}`) : '#',
            label: followed ? `${row.name}, following` : `Follow ${row.name}`,
            title: row.name,
            meta: [row.start_year, row.publisher, followed ? 'Following' : (row.issue_count ? `${row.issue_count} issues` : null)],
            cover: row.cover_url,
            imgAttrs: {referrerpolicy: 'no-referrer'},
        });
        if (!followed) card.querySelector('.book > a').addEventListener('click', async (e) => {
            e.preventDefault();
            if (card.classList.contains('is-busy')) return;
            card.classList.add('is-busy');
            try {
                // New issues to start with; the series page's ⋯ changes it.
                const data = await apiFetch('/comics/api/series', {method: 'POST', body: {provider: row.provider, provider_id: row.provider_id, monitor: 'future'}});
                window.location = data.url;
            } catch (err) {
                showToast(err.message, 'error');
                card.classList.remove('is-busy');
            }
        });
        return card;
    }

    async function fill(kind, q, mine, make, emptyNote) {
        const section = sections[kind];
        const results = section.querySelector('.get-results');
        results.dataset.loading = '1';
        results.replaceChildren(...skeletons(PHONE.matches ? 4 : 6));
        section.querySelector('.get-note').textContent = '';
        section.querySelector('[data-count]').textContent = '';
        section.hidden = shown !== 'all' && shown !== kind;
        let data;
        try {
            data = await apiFetch(`/api/get/search/${kind}?q=${encodeURIComponent(q)}`);
        } catch (e) {
            data = {results: [], error: e.message};
        }
        if (mine !== generation) return;  // a newer search has started
        delete results.dataset.loading;
        results.replaceChildren(...data.results.map(make));
        section.querySelector('.get-note').textContent = data.error || (data.results.length ? '' : emptyNote);
        section.querySelector('[data-count]').textContent = data.results.length || '';
        applyShow();
    }

    function search() {
        const q = input.value.trim();
        if (!q) return;
        const mine = ++generation;
        history.replaceState(null, '', `?q=${encodeURIComponent(q)}`);
        // Each source fills its section as soon as it answers.
        fill('books', q, mine, bookCard, 'No books by that name on Open Library.');
        fill('comics', q, mine, comicCard, 'No comic series by that name.');
    }

    show.addEventListener('click', (e) => {
        const button = e.target.closest('[data-show]');
        if (button) setShown(button.dataset.show);
    });
    document.querySelectorAll('.section__link, .get-all').forEach(b => b.addEventListener('click', () => { setShown(b.dataset.show); window.scrollTo({top: 0, behavior: 'smooth'}); }));
    PHONE.addEventListener?.('change', applyShow);
    form.addEventListener('submit', (e) => { e.preventDefault(); input.blur(); search(); });
    if (input.value.trim()) search();
}

// --- Downloads ---------------------------------------------------------------

let boostUntil = 0;   // check every 5 s for a minute after doing something
let refreshDownloads = () => {};
function boost() {
    boostUntil = Date.now() + 60000;
    refreshDownloads();
}

async function run(work, done) {
    try {
        const result = await work();
        if (done) done(result);
        return result;
    } catch (err) {
        showToast(err.message, 'error');
        return null;
    }
}

function initDownloads() {
    initWanted();
    initDownloadLists();
    initImport();
}

// Wanted: compact rows, each with a ⋯ menu; a comic series' row acts on all
// its issues at once.
function initWanted() {
    const section = document.getElementById('wanted');
    const canSearch = Boolean(section.dataset.canSearch);

    function removeRows(rows) {
        rows.forEach(row => {
            const series = row.closest('.entry-group');
            row.remove();
            if (series && !series.querySelector('[data-item-id]')) series.remove();
        });
        section.querySelectorAll('.sub-head').forEach(heading => {
            const list = heading.nextElementSibling;
            const left = list.querySelectorAll('[data-item-id]').length;
            if (!left) { heading.remove(); list.remove(); } else heading.querySelector('[data-count]').textContent = left;
        });
    }

    // While a row is being looked for, its date says so.
    async function looking(row, work) {
        const side = row.querySelector('.entry__side');
        const was = side ? side.textContent : '';
        if (side) side.textContent = 'Looking…';
        try { return await work(); } finally { if (side && row.isConnected) side.textContent = was; }
    }

    function findItem(row) {
        looking(row, () => run(() => apiFetch(`/api/wanted/${row.dataset.kind}/${row.dataset.itemId}/search`, {method: 'POST'}), data => {
            if (data.found === false) return showToast(data.message);
            showToast(`Downloading ${row.dataset.label}`, 'success');
            removeRows([row]);
            boost();
        }));
    }

    function itemMenu(row, anchor) {
        const book = row.dataset.kind === 'book';
        return [
            canSearch ? {label: 'Find now', onClick: () => findItem(row)} : null,
            canSearch ? {label: 'Choose a release…', onClick: () => pickRelease({kind: row.dataset.kind, id: row.dataset.itemId, label: row.dataset.label, onGrab: () => { removeRows([row]); boost(); }})} : null,
            book
                ? {label: 'Stop looking…', danger: true, onClick: () => confirmMenu(anchor, `Stop looking for ${row.dataset.label}?`, [{label: 'Keep looking'}, {label: 'Stop looking', danger: true, onClick: () => run(() => apiFetch(`/api/book-requests/${row.dataset.itemId}`, {method: 'DELETE'}), () => removeRows([row]))}])}
                : {label: 'Skip', onClick: () => run(() => apiFetch(`/comics/api/issues/${row.dataset.itemId}`, {method: 'PATCH', body: {status: 'skipped'}}), () => removeRows([row]))},
        ];
    }

    function seriesMenu(series) {
        const rows = [...series.querySelectorAll('[data-item-id]')];
        const many = rows.length > 1;
        return [
            canSearch ? {label: many ? `Find all ${rows.length} now` : 'Find now', onClick: () => looking(series.querySelector('summary'), () => run(() => apiFetch(`/comics/api/series/${series.dataset.seriesId}/search`, {method: 'POST'}), data => {
                if (data.error) showToast(data.grabbed ? `Found ${data.grabbed}, but ${data.error}` : data.error, 'error');
                else showToast(data.grabbed ? `Downloading ${data.grabbed} issue${data.grabbed === 1 ? '' : 's'}` : 'Nothing new yet', data.grabbed ? 'success' : 'info');
                if (data.grabbed) setTimeout(() => window.location.reload(), 1200);
            }))} : null,
            {label: many ? `Skip all ${rows.length}` : 'Skip', onClick: () => run(() => apiFetch('/comics/api/issues/bulk', {method: 'POST', body: {ids: rows.map(r => Number(r.dataset.itemId)), status: 'skipped'}}), () => removeRows(rows))},
            {label: 'Open the series', href: appUrl(`/comics/series/${series.dataset.seriesId}`)},
        ];
    }

    section.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action]');
        if (!button) return;
        if (button.dataset.action === 'search-all') {
            await run(() => apiFetch('/api/jobs/search', {method: 'POST'}), () => { showToast('Looking for everything wanted…'); boost(); });
            return;
        }
        if (button.dataset.action === 'show-more') {
            button.closest('.entries').querySelectorAll('[data-more]').forEach(r => { r.hidden = false; });
            button.closest('.entry--more').remove();
            return;
        }
        e.preventDefault();  // a ⋯ in a series' summary shouldn't fold it
        const row = button.closest('[data-item-id]');
        openMenu(button, row ? itemMenu(row, button) : seriesMenu(button.closest('.entry-group')));
    });
}

function initDownloadLists() {
    const activeSection = document.getElementById('activeSection');
    const activeList = document.getElementById('activeList');
    const attentionList = document.getElementById('attentionList');
    const historyList = document.getElementById('historyList');
    const historyCount = document.getElementById('historyCount');
    const statusLine = document.getElementById('statusLine');
    let misses = 0;

    function stateOf(d, where) {
        const percent = Math.round((d.progress || 0) * 100);
        if (where === 'active') {
            if (d.status === 'importing') return ['Adding to the library', null];
            if (d.client === 'blackhole') return ['Waiting for your download client', null];
            if (d.stalled) return [`Stalled at ${percent}%`, 'is-bad'];
            return [`${percent}%`, null];
        }
        if (d.status === 'done') return [d.kind === 'book' ? 'Added to Books' : 'Added to Comics', 'is-good'];
        return d.error === 'Cancelled.' ? ['Cancelled', null] : ['Failed', 'is-bad'];
    }

    function stopLooking(d, anchor) {
        if (d.kind === 'book') {
            confirmMenu(anchor, `Stop looking for ${d.item.label}?`, [{label: 'Keep looking'}, {label: 'Stop looking', danger: true, onClick: () => act(`/api/book-requests/${d.item.id}`, 'DELETE', 'Stopped looking')}]);
        } else {
            act(`/comics/api/issues/${d.item.id}`, 'PATCH', 'Skipped', {status: 'skipped'});
        }
    }

    // A download as a row: what it's for, then its state and details; ⋯
    // holds what you can do about it.
    function downloadRow(d, where) {
        const percent = Math.round((d.progress || 0) * 100);
        const [state, tone] = stateOf(d, where);
        const label = d.item ? d.item.label : 'Removed';
        const retry = d.item ? {label: 'Try another release', onClick: () => act(`/api/downloads/${d.id}/retry`, 'POST', 'Looking for another release')} : null;
        const actions = where === 'active'
            ? [d.stalled ? retry : null, {label: 'Cancel…', danger: true, onClick: () => confirmMenu(more, `Cancel ${label}?`, [{label: 'Keep downloading'}, {label: 'Cancel the download', danger: true, onClick: () => act(`/api/downloads/${d.id}/cancel`, 'POST', 'Cancelled')}])}]
            : where === 'attention'
                ? [retry, d.item ? {label: 'Stop looking…', danger: true, onClick: () => stopLooking(d, more)} : null, {label: 'Remove from history', onClick: () => act(`/api/downloads/${d.id}`, 'DELETE', 'Removed')}]
                : [d.status === 'failed' && d.item && d.error !== 'Cancelled.' ? retry : null, {label: 'Remove from history', onClick: () => act(`/api/downloads/${d.id}`, 'DELETE', 'Removed')}];
        const more = h('button', {type: 'button', class: 'entry__more', 'aria-label': `More for ${label}`, dataset: {menuAnchor: ''}, onclick: (e) => openMenu(e.currentTarget, actions)}, h('i', {class: 'fas fa-ellipsis-h', 'aria-hidden': 'true'}));
        const showError = d.error && d.error !== 'Cancelled.' && where !== 'active';
        return h('li', {class: 'entry', title: d.title},
            h('div', {class: 'entry__main'},
                h('span', {class: 'entry__title'}, d.item ? h('a', {href: d.item.url}, d.item.label) : h('span', {class: 'muted'}, 'Removed')),
                h('span', {class: 'entry__meta'}, h('strong', {class: tone}, state), ' · ', [d.kind === 'book' ? 'Book' : 'Comic', d.indexer, formatSize(d.size), timeAgo(d.updated_at || d.created_at)].filter(Boolean).join(' · ')),
                showError ? h('span', {class: 'entry__error'}, d.error) : null,
                where === 'active' && d.client !== 'blackhole' && d.status !== 'importing' ? h('span', {class: 'entry__bar'}, h('span', {style: `width: ${percent}%`})) : null),
            h('span'),
            more);
    }

    async function act(path, method, done, body) {
        await run(() => apiFetch(path, {method, body}), (data) => showToast(data && data.found === false ? data.message : done, data && data.found === false ? 'info' : 'success'));
        boost();
    }

    function showStatus(text) {
        statusLine.textContent = text || '';
        statusLine.hidden = !text;
    }

    async function refresh() {
        let data;
        try {
            data = await apiFetch('/api/downloads');
        } catch (e) {
            misses += 1;
            if (misses >= 2) {
                showStatus('Can’t reach the library. Retrying…');
                document.body.classList.add('is-stale');
            }
            return;
        }
        misses = 0;
        document.body.classList.remove('is-stale');
        showStatus(data.clients.length ? data.clients.join(' ') : (data.paused ? 'Downloads are paused. They’ll pick up again in a moment.' : ''));
        activeSection.hidden = !data.active.length && !data.attention.length;
        attentionList.replaceChildren(...data.attention.map(d => downloadRow(d, 'attention')));
        activeList.replaceChildren(...data.active.map(d => downloadRow(d, 'active')));
        historyList.replaceChildren(...(data.history.length ? data.history.map(d => downloadRow(d, 'history')) : [h('li', {class: 'empty-line'}, 'Nothing yet.')]));
        historyCount.textContent = data.history.length || '';
    }
    refreshDownloads = refresh;

    // Every 5 s while something is downloading (or just after you did
    // something), every 10 s otherwise.
    async function poll() {
        if (!document.hidden) await refresh();
        const quick = !activeSection.hidden || Date.now() < boostUntil;
        setTimeout(poll, quick ? 5000 : 10000);
    }
    poll();
}


// --- Import: books and comics from your computer ----------------------------

function initImport() {
    const list = document.getElementById('importList');
    const waiting = document.getElementById('importWaiting');
    const input = document.getElementById('importInput');
    const series = JSON.parse(document.getElementById('seriesData').textContent);

    function importRow(file) {
        const startOn = file.guess || (file.series && file.series.id) || '';
        const seriesSelect = h('select', {class: 'meta-input', 'aria-label': 'Series'},
            h('option', {value: ''}, 'Choose a series…'),
            series.map(([id, name]) => h('option', {value: id, selected: id === startOn}, name)),
            h('option', {value: 'new'}, 'A new series (from the file)…'));
        const number = h('input', {class: 'meta-input input--short', type: 'text', inputmode: 'decimal', value: file.parsed.number || '', 'aria-label': 'Issue number', placeholder: '#'});
        const newName = h('input', {class: 'meta-input', type: 'text', value: file.parsed.series || '', 'aria-label': 'Series name', hidden: true});
        const go = h('button', {type: 'button', class: 'btn btn-primary', disabled: !startOn, onclick: async (e) => {
            const body = {path: file.path, number: number.value};
            if (seriesSelect.value === 'new') body.new_series = newName.value;
            else body.series_id = Number(seriesSelect.value);
            e.currentTarget.textContent = 'Adding…';
            await busy(e.currentTarget, async () => {
                const issue = await run(() => apiFetch('/api/import/file', {method: 'POST', body}));
                if (issue) {
                    showToast(`Filed as ${issue.series} #${issue.number}`, 'success', {label: 'Open', onClick: () => { window.location = appUrl(`/comics/series/${issue.series_id}`); }});
                    load();
                }
            });
        }}, 'Add');
        seriesSelect.addEventListener('change', () => {
            newName.hidden = seriesSelect.value !== 'new';
            go.disabled = !seriesSelect.value;
        });
        const remove = h('button', {type: 'button', class: 'btn btn-ghost danger-text', onclick: (e) => confirmMenu(e.currentTarget, `Delete ${file.path}? This can’t be undone.`, [{label: 'Keep it'}, {label: 'Delete the file', danger: true, onClick: () => run(() => apiFetch(`/api/import/file?path=${encodeURIComponent(file.path)}`, {method: 'DELETE'}), () => { showToast(`Deleted ${file.path}`); load(); })}])}, 'Delete');
        const guess = [file.parsed.series, file.parsed.number ? `#${file.parsed.number}` : null].filter(Boolean).join(' ');
        return h('li', {class: 'entry entry--import'},
            h('div', {class: 'entry__main'},
                h('span', {class: 'entry__title'}, guess ? `${guess}?` : file.path),
                h('span', {class: 'entry__meta'}, [guess ? file.path : null, formatSize(file.size)].filter(Boolean).join(' · ')),
                h('span', {class: 'entry__hint'}, file.issue ? `Will be filed as ${file.issue.label}` : file.reason),
                h('div', {class: 'entry__controls'}, seriesSelect, newName, number, go, remove)));
    }

    async function load() {
        try {
            const data = await apiFetch('/api/import');
            waiting.hidden = !data.files.length;
            document.getElementById('importScan').hidden = !data.files.length;
            list.replaceChildren(...data.files.map(importRow));
        } catch (e) {
            waiting.hidden = false;
            list.replaceChildren(h('li', {class: 'empty-line'}, e.message));
        }
    }

    function describe(data) {
        return [`Added ${data.imported.length}.`, data.unmatched.length ? `${data.unmatched.length} need${data.unmatched.length === 1 ? 's' : ''} a series.` : null, data.failed.length ? `${data.failed.length} couldn’t be opened.` : null].filter(Boolean).join(' ');
    }

    async function send(fileList) {
        const files = [...fileList].filter(f => /\.(epub|cbz|cbr|cb7|zip|rar|7z)$/i.test(f.name));
        if (!files.length) return showToast('Those aren’t books or comics.', 'error');
        const form = new FormData();
        files.forEach(f => form.append('files', f));
        showToast(`Adding ${files.length} file${files.length === 1 ? '' : 's'}…`);
        await run(() => apiFetch('/api/import/upload', {method: 'POST', form}), data => showToast(describe(data), data.failed.length ? 'error' : 'success'));
        load();
    }

    document.getElementById('importPick').addEventListener('click', () => input.click());
    input.addEventListener('change', () => { send(input.files); input.value = ''; });
    enableDropZone(document.getElementById('dropZone'), send);
    document.getElementById('importScan').addEventListener('click', async (e) => {
        e.currentTarget.textContent = 'Matching…';
        await busy(e.currentTarget, () => run(() => apiFetch('/api/import/scan', {method: 'POST'}), data => showToast(describe(data), 'success')));
        load();
    });
    load();
}


const DOWNLOAD_PAGES = {get: initGet, downloads: initDownloads};
document.addEventListener('DOMContentLoaded', () => {
    const init = DOWNLOAD_PAGES[document.body.dataset.page];
    if (init) init();
});

})();
