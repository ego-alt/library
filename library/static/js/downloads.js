// Downloads: following everything on its way into the library, the files
// that need a series, and Settings folded at the foot. Also the release
// chooser the comics series page uses. Asking for books and following series
// is under the shelves' search (get.js); adding files is the shelves' +.
// Helpers are in ui.js.
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
    initSettingsFold();
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


// --- Needs a series: comic files waiting in the import folder (import.js) ---

function initImport() {
    const section = document.getElementById('import');
    const list = document.getElementById('importList');
    const load = async () => { section.hidden = !(await comicImport.fillWaiting(list, load)); };
    document.getElementById('importScan').addEventListener('click', async (e) => {
        e.currentTarget.textContent = 'Matching…';
        await busy(e.currentTarget, () => run(() => apiFetch('/api/import/scan', {method: 'POST'}), data => showToast(comicImport.describe(data), 'success')));
        load();
    });
    load();
}

// --- Settings, folded at the foot: opened by a link to one of its parts ---

function initSettingsFold() {
    const fold = document.getElementById('settings');
    const open = (hash) => {
        fold.open = true;
        const target = hash && document.querySelector(hash);
        (target || fold).scrollIntoView({behavior: 'smooth', block: 'start'});
    };
    const fromHash = () => { if (location.hash && (location.hash === '#settings' || fold.querySelector(location.hash))) open(location.hash); };
    document.addEventListener('click', (e) => {
        const link = e.target.closest('[data-open-settings]');
        if (!link) return;
        e.preventDefault();
        history.replaceState(null, '', link.getAttribute('href'));
        open(link.getAttribute('href'));
    });
    window.addEventListener('hashchange', fromHash);
    fromHash();
}


const DOWNLOAD_PAGES = {downloads: initDownloads};
document.addEventListener('DOMContentLoaded', () => {
    const init = DOWNLOAD_PAGES[document.body.dataset.page];
    if (init) init();
});

})();
