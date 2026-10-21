// Get and Downloads: asking for books and comics, and following everything
// on its way into the library. Also the release picker the comics series page
// uses. Helpers are in ui.js.
(() => {

// --- Picking a release by hand, for a book request or a comic issue ----------

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

/** Every release the indexers have for a wanted item, with why the rejected
 * ones don't fit; Grab sends one to the download client. */
async function pickRelease({kind, id, label, onGrab}) {
    const overlay = pickerOverlay();
    const list = overlay.querySelector('#releaseList');
    const status = overlay.querySelector('#releasesStatus');
    overlay.querySelector('#releasesTitle').textContent = `Releases for ${label}`;
    status.textContent = 'Asking the indexers…';
    list.replaceChildren();
    overlay.style.display = 'flex';
    try {
        const data = await apiFetch(`/api/wanted/${kind}/${id}/releases`);
        const fits = data.releases.filter(r => r.score >= 0).length;
        status.textContent = (data.releases.length ? `${fits} of ${data.releases.length} fit.` : 'The indexers have nothing for it.') + (data.errors.length ? ` ${data.errors.join(' ')}` : '');
        list.append(...data.releases.map((r, index) => h('li', {class: r.score >= 0 ? 'release' : 'release is-rejected'},
            h('div', {class: 'release__text'},
                h('strong', {}, r.title),
                h('span', {class: 'text-muted'}, [r.indexer, r.protocol === 'torrent' ? `${r.seeders ?? '?'} seeders` : 'usenet', formatSize(r.size), r.published, r.note].filter(Boolean).join(' · '))),
            h('button', {type: 'button', class: r.score >= 0 ? 'btn btn-primary' : 'btn btn-secondary', onclick: (e) => grab(e.currentTarget, index, data.token)}, 'Grab'))));
    } catch (e) {
        status.textContent = e.message;
    }

    async function grab(button, index, token) {
        button.textContent = 'Sending…';
        await busy(button, async () => {
            try {
                const data = await apiFetch(`/api/wanted/${kind}/${id}/grab`, {method: 'POST', body: {token, index}});
                overlay.style.display = 'none';
                showToast(`Sent ${data.download.title} to ${data.download.client}`, 'success');
                if (onGrab) onGrab(data);
            } catch (e) { showToast(e.message, 'error'); }
        });
    }
}

window.pickRelease = pickRelease;

// --- Get: one search for books and comics -----------------------------------

const BOOK_FLAGS = {have: 'In your library', wanted: 'Requested', snatched: 'Downloading', downloaded: 'In your library', skipped: 'Get'};

function initGet() {
    const form = document.getElementById('getForm');
    const input = document.getElementById('getQuery');
    const status = document.getElementById('getStatus');
    const bookSection = document.getElementById('bookResults');
    const comicSection = document.getElementById('comicResults');
    const monitor = document.getElementById('monitorChoice');
    const show = form.querySelector('[aria-label="Show"]');
    let shown = 'all';

    function applyShow() {
        const has = section => section.querySelector('.get-results').children.length || section.querySelector('.get-note').textContent;
        bookSection.hidden = shown === 'comics' || !has(bookSection);
        comicSection.hidden = shown === 'books' || !has(comicSection);
    }

    function flag(text, on) {
        return h('span', {class: `cover-flag cover-flag--action${on ? ' is-on' : ''}`}, text);
    }

    function bookCard(book) {
        const done = book.status && book.status !== 'skipped';
        const card = coverCard({
            href: '#',
            label: done ? `${book.title}: ${BOOK_FLAGS[book.status]}` : `Get ${book.title}`,
            title: book.title,
            meta: [book.author, book.year],
            cover: book.cover_url,
            imgAttrs: {referrerpolicy: 'no-referrer'},
            extras: [flag(done ? BOOK_FLAGS[book.status] : 'Get', done)],
        });
        card.querySelector('.book > a').addEventListener('click', async (e) => {
            e.preventDefault();
            if (done || card.classList.contains('is-busy')) return;
            card.classList.add('is-busy');
            const f = card.querySelector('.cover-flag');
            f.textContent = 'Asking…';
            try {
                const data = await apiFetch('/api/get/books', {method: 'POST', body: book});
                book.status = data.status;
                f.textContent = BOOK_FLAGS[data.status] || 'Requested';
                f.classList.add('is-on');
                showToast(`Getting ${book.title}; it shows up in Downloads`, 'success');
            } catch (err) {
                f.textContent = 'Get';
                showToast(err.message, 'error');
            }
            card.classList.remove('is-busy');
        });
        return card;
    }

    function comicCard(row) {
        const followed = Boolean(row.followed_id);
        const card = coverCard({
            href: followed ? appUrl(`/comics/series/${row.followed_id}`) : '#',
            label: followed ? `${row.name}, followed` : `Follow ${row.name}`,
            title: row.name,
            meta: [row.start_year, row.publisher, row.issue_count ? `${row.issue_count} issues` : null],
            cover: row.cover_url,
            imgAttrs: {referrerpolicy: 'no-referrer'},
            attrs: {title: row.description ? (row.description.length > 300 ? `${row.description.slice(0, 300)}…` : row.description) : null},
            extras: [flag(followed ? 'Following' : 'Follow', followed)],
        });
        if (!followed) card.querySelector('.book > a').addEventListener('click', async (e) => {
            e.preventDefault();
            if (card.classList.contains('is-busy')) return;
            card.classList.add('is-busy');
            card.querySelector('.cover-flag').textContent = 'Adding…';
            try {
                const data = await apiFetch('/comics/api/series', {method: 'POST', body: {provider: row.provider, provider_id: row.provider_id, monitor: monitor.value}});
                window.location = data.url;
            } catch (err) {
                showToast(err.message, 'error');
                card.classList.remove('is-busy');
                card.querySelector('.cover-flag').textContent = 'Follow';
            }
        });
        return card;
    }

    function fill(section, cards, note) {
        section.querySelector('.get-results').replaceChildren(...cards);
        section.querySelector('.get-note').textContent = note || '';
        section.querySelector('[data-count]').textContent = cards.length || '';
    }

    async function search() {
        const q = input.value.trim();
        if (!q) return;
        status.textContent = 'Looking…';
        history.replaceState(null, '', `?q=${encodeURIComponent(q)}`);
        try {
            const data = await apiFetch(`/api/get/search?q=${encodeURIComponent(q)}`);
            fill(bookSection, data.books.map(bookCard), data.errors.books || (data.books.length ? '' : 'No books by that name on Open Library.'));
            fill(comicSection, data.comics.map(comicCard), data.errors.comics || (data.comics.length ? '' : 'No comic series by that name.'));
            status.textContent = '';
            applyShow();
        } catch (e) {
            status.textContent = e.message;
        }
    }

    show.addEventListener('click', (e) => {
        const button = e.target.closest('[data-show]');
        if (!button) return;
        setRadio(show, button);
        shown = button.dataset.show;
        applyShow();
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); input.blur(); search(); });
    if (input.value.trim()) search();
}

// --- Downloads ---------------------------------------------------------------

function initDownloads() {
    initWanted();
    initDownloadLists();
    initImport();
    document.getElementById('jobList').addEventListener('click', async (e) => {
        const button = e.target.closest('[data-run]');
        if (!button) return;
        await apiFetch(`/api/jobs/${button.dataset.run}`, {method: 'POST'});
        showToast('Starting', 'success');
    });
}

function showJobs(worker) {
    document.querySelectorAll('#jobList [data-job]').forEach(rowEl => {
        const job = worker[rowEl.dataset.job];
        const msg = rowEl.querySelector('.job-msg');
        const pending = (worker.pending || []).includes(rowEl.dataset.job);
        msg.textContent = pending ? 'Starting…' : (job ? `${job.message} (${timeAgo(job.at)})` : 'Not run yet');
        msg.classList.toggle('danger-text', Boolean(job && !job.ok));
    });
    document.getElementById('workerState').textContent = worker.alive ? 'These run on their own; Run starts one now.' : 'The worker hasn’t checked in for a while; it starts when the app gets its first visit after a restart.';
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

    async function run(work, done) {
        try {
            const result = await work();
            if (done) done(result);
        } catch (err) { showToast(err.message, 'error'); }
    }

    function searchItem(row) {
        showToast(`Searching for ${row.dataset.label}…`);
        run(() => apiFetch(`/api/wanted/${row.dataset.kind}/${row.dataset.itemId}/search`, {method: 'POST'}), data => {
            showToast(`Grabbed ${data.download.title}`, 'success');
            removeRows([row]);
        });
    }

    function itemMenu(row) {
        const book = row.dataset.kind === 'book';
        return [
            canSearch ? {label: 'Search now', onClick: () => searchItem(row)} : null,
            canSearch ? {label: 'Pick a release…', onClick: () => pickRelease({kind: row.dataset.kind, id: row.dataset.itemId, label: row.dataset.label, onGrab: () => removeRows([row])})} : null,
            book
                ? {label: 'Remove', danger: true, onClick: () => { if (confirm(`Stop getting ${row.dataset.label}?`)) run(() => apiFetch(`/api/book-requests/${row.dataset.itemId}`, {method: 'DELETE'}), () => removeRows([row])); }}
                : {label: 'Skip', onClick: () => run(() => apiFetch(`/comics/api/issues/${row.dataset.itemId}`, {method: 'PATCH', body: {status: 'skipped'}}), () => removeRows([row]))},
        ];
    }

    function seriesMenu(series) {
        const rows = [...series.querySelectorAll('[data-item-id]')];
        const many = rows.length > 1;
        return [
            canSearch ? {label: many ? `Search for all ${rows.length}` : 'Search now', onClick: () => {
                showToast(`Searching for ${series.dataset.label}…`);
                run(() => apiFetch(`/comics/api/series/${series.dataset.seriesId}/search`, {method: 'POST'}), data => {
                    showToast(data.grabbed ? `Grabbed ${data.grabbed}` : 'Nothing on the indexers yet', data.grabbed ? 'success' : 'info');
                    if (data.grabbed) window.location.reload();
                });
            }} : null,
            {label: many ? `Skip all ${rows.length}` : 'Skip', onClick: () => run(() => apiFetch('/comics/api/issues/bulk', {method: 'POST', body: {ids: rows.map(r => Number(r.dataset.itemId)), status: 'skipped'}}), () => removeRows(rows))},
            {label: 'Open the series', href: appUrl(`/comics/series/${series.dataset.seriesId}`)},
        ];
    }

    section.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action]');
        if (!button) return;
        if (button.dataset.action === 'search-all') {
            await apiFetch('/api/jobs/search', {method: 'POST'});
            showToast('Searching; grabs show up at the top of this page.', 'success');
            return;
        }
        e.preventDefault();  // a ⋯ in a series' summary shouldn't fold it
        const row = button.closest('[data-item-id]');
        openMenu(button, row ? itemMenu(row) : seriesMenu(button.closest('.entry-group')));
    });
}

function initDownloadLists() {
    const activeSection = document.getElementById('activeSection');
    const activeList = document.getElementById('activeList');
    const historyList = document.getElementById('historyList');
    const historyCount = document.getElementById('historyCount');

    // A download as a row: what it's for, then its state and details; ⋯ holds
    // Cancel, or for finished ones Try another and Remove.
    function downloadRow(d, active) {
        const percent = Math.round((d.progress || 0) * 100);
        const state = active
            ? (d.status === 'importing' ? 'Importing' : d.client === 'blackhole' ? 'Waiting for the file' : `${percent}%`)
            : (d.status === 'done' ? 'Done' : 'Failed');
        const actions = active
            ? [{label: 'Cancel', danger: true, onClick: () => act(`/api/downloads/${d.id}/cancel`, 'POST', 'Cancelled')}]
            : [d.status === 'failed' && d.item ? {label: 'Try another release', onClick: () => act(`/api/downloads/${d.id}/retry`, 'POST', 'Grabbed another')} : null,
               {label: 'Remove from history', onClick: () => act(`/api/downloads/${d.id}`, 'DELETE', 'Removed')}];
        const more = h('button', {type: 'button', class: 'entry__more', 'aria-label': 'More', dataset: {menuAnchor: ''}, onclick: (e) => openMenu(e.currentTarget, actions)}, h('i', {class: 'fas fa-ellipsis-h', 'aria-hidden': 'true'}));
        return h('li', {class: 'entry', title: d.title},
            h('div', {class: 'entry__main'},
                h('span', {class: 'entry__title'}, d.item ? h('a', {href: d.item.url}, d.item.label) : h('span', {class: 'muted'}, 'Removed')),
                h('span', {class: 'entry__meta'}, h('strong', {class: d.status === 'failed' ? 'is-bad' : d.status === 'done' ? 'is-good' : null}, state), ' · ', [d.kind === 'book' ? 'Book' : 'Comic', d.indexer, formatSize(d.size), timeAgo(d.updated_at || d.created_at)].filter(Boolean).join(' · ')),
                d.error ? h('span', {class: 'entry__error'}, d.error) : null,
                active && d.client !== 'blackhole' ? h('span', {class: 'entry__bar'}, h('span', {style: `width: ${percent}%`})) : null),
            h('span'),
            more);
    }

    async function act(path, method, done) {
        try {
            await apiFetch(path, {method});
            showToast(done, 'success');
        } catch (e) { showToast(e.message, 'error'); }
        refresh();
    }

    async function refresh() {
        let data;
        try { data = await apiFetch('/api/downloads'); } catch (e) { return; }
        activeSection.hidden = !data.active.length;
        activeList.replaceChildren(...data.active.map(d => downloadRow(d, true)));
        historyList.replaceChildren(...(data.history.length ? data.history.map(d => downloadRow(d, false)) : [h('li', {class: 'empty-line'}, 'Nothing yet.')]));
        showJobs(data.worker || {});
        const failed = data.history.filter(d => d.status === 'failed').length;
        historyCount.textContent = data.history.length ? (failed ? `${data.history.length} · ${failed} failed` : String(data.history.length)) : '';
    }

    // Every 5 s while something is downloading, every 30 s otherwise.
    async function poll() {
        if (!document.hidden) await refresh();
        setTimeout(poll, activeSection.hidden ? 30000 : 5000);
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
        const seriesSelect = h('select', {class: 'input'},
            h('option', {value: ''}, 'Pick a series…'),
            series.map(([id, name]) => h('option', {value: id, selected: file.series && file.series.id === id}, name)),
            h('option', {value: 'new'}, 'A new series (from the file)…'));
        const number = h('input', {class: 'input input--short', type: 'text', value: file.parsed.number || '', 'aria-label': 'Issue number', placeholder: '#'});
        const newName = h('input', {class: 'input', type: 'text', value: file.parsed.series || '', 'aria-label': 'Series name', hidden: true});
        seriesSelect.addEventListener('change', () => { newName.hidden = seriesSelect.value !== 'new'; });
        const go = h('button', {type: 'button', class: 'btn btn-primary', onclick: async (e) => {
            const body = {path: file.path, number: number.value};
            if (seriesSelect.value === 'new') body.new_series = newName.value;
            else if (seriesSelect.value) body.series_id = Number(seriesSelect.value);
            else return showToast('Pick a series first.', 'error');
            e.currentTarget.textContent = 'Importing…';
            await busy(e.currentTarget, async () => {
                try {
                    await apiFetch('/api/import/file', {method: 'POST', body});
                    showToast('Imported', 'success');
                    load();
                } catch (err) { showToast(err.message, 'error'); }
            });
        }}, 'Import');
        const remove = h('button', {type: 'button', class: 'btn btn-ghost danger-text', onclick: async () => {
            if (!confirm(`Delete ${file.path}?`)) return;
            await apiFetch(`/api/import/file?path=${encodeURIComponent(file.path)}`, {method: 'DELETE'});
            load();
        }}, 'Delete');
        return h('li', {class: 'entry entry--import'},
            h('div', {class: 'entry__main'},
                h('span', {class: 'entry__title'}, file.path),
                h('span', {class: 'entry__meta'}, [formatSize(file.size), file.issue ? `Matches ${file.issue.label}; it's filed at the next import` : file.reason].filter(Boolean).join(' · ')),
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

    async function send(fileList) {
        const files = [...fileList].filter(f => /\.(epub|cbz|cbr|cb7|zip|rar|7z)$/i.test(f.name));
        if (!files.length) return showToast('Those aren’t books or comics.', 'error');
        const form = new FormData();
        files.forEach(f => form.append('files', f));
        showToast(`Importing ${files.length} file${files.length === 1 ? '' : 's'}…`);
        try {
            const data = await apiFetch('/api/import/upload', {method: 'POST', form});
            showToast(`Imported ${data.imported.length}${data.unmatched.length ? `; ${data.unmatched.length} to match by hand` : ''}${data.failed.length ? `; ${data.failed.length} unreadable` : ''}`, data.failed.length ? 'error' : 'success');
        } catch (e) { showToast(e.message, 'error'); }
        load();
    }

    document.getElementById('importPick').addEventListener('click', () => input.click());
    input.addEventListener('change', () => { send(input.files); input.value = ''; });
    enableDropZone(document.getElementById('dropZone'), send);
    document.getElementById('importScan').addEventListener('click', async (e) => {
        e.currentTarget.textContent = 'Matching…';
        await busy(e.currentTarget, async () => {
            try {
                const data = await apiFetch('/api/import/scan', {method: 'POST'});
                showToast(`Imported ${data.imported.length}`, 'success');
            } catch (err) { showToast(err.message, 'error'); }
        });
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
