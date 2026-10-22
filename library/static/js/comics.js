// Comics pages: one small module per page, picked by <body data-page>.

const comicsApi = (path, options) => apiFetch(`/comics/api${path}`, options);

// "/" puts you in the search box, as on the books shelf.
function bindSearchKey(input) {
    if (!input) return;
    document.addEventListener('keydown', (e) => {
        if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
        e.preventDefault();
        input.focus();
    });
}

// --- The wall of series: one search box, filtered here since every series
// is on the page. ---

function initSeries() {
    const grid = document.getElementById('library');
    if (!grid) return;
    const search = document.getElementById('librarySearch');
    const empty = document.getElementById('emptyState');
    const cards = [...grid.children];
    bindSearchKey(search);

    function apply() {
        const q = search.value.trim().toLowerCase();
        let shown = 0;
        for (const card of cards) {
            card.hidden = Boolean(q) && !card.dataset.name.includes(q);
            if (!card.hidden) shown += 1;
        }
        empty.hidden = shown > 0;
        if (!shown) {
            empty.querySelector('h3').textContent = `Nothing matches "${search.value.trim()}"`;
            empty.querySelector('p').textContent = 'Try a different word, or clear the search.';
        }
    }

    search.addEventListener('input', apply);
    search.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            search.blur();  // drops the phone keyboard so the results show
        } else if (e.key === 'Escape' && search.value) {
            e.stopPropagation();
            search.value = '';
            apply();
        }
    });
}

// --- One series: its issues as covers, each with a ⋯ menu (read, mark read,
// download; for admins also find, choose a release, want or skip, add or
// replace the file). Admins see the missing ones, faded, with what each is
// waiting on in its caption. ---

const MISSING_STATE = {wanted: 'Wanted', snatched: 'Downloading', skipped: 'Skipped'};
const MONITOR_LABELS = [['future', 'Get new issues'], ['all', 'Get all missing issues'], ['none', 'Get none (I’ll choose)']];

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
    let selecting = false;  // admins' Select mode
    const selected = new Set();

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
        const meta = el && el.querySelector('.book-caption__author');
        if (!meta) return;
        let state = '';
        if (issue.has_file) state = issue.finished ? 'Read' : (issue.page && issue.pages ? `${Math.floor(100 * (issue.page + 1) / issue.pages)}%` : '');
        else state = issue.released ? (MISSING_STATE[issue.status] || issue.status) : '';
        meta.textContent = (issue.released || issue.has_file ? [formatDate(issue.date), state] : [`Out ${formatDate(issue.date)}`]).filter(Boolean).join(' · ');
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

    if (wall) wall.addEventListener('click', (e) => {
        const el = e.target.closest('[data-issue-id]');
        if (!el) return;
        const issue = issues.get(el.dataset.issueId);
        if (selecting) {
            e.preventDefault();
            if (issue.has_file || issue.status === 'snatched') return;
            el.classList.toggle('is-selected');
            el.classList.contains('is-selected') ? selected.add(issue.id) : selected.delete(issue.id);
            updateBulk();
            return;
        }
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
            {label: issue.finished ? 'Read again' : (issue.page ? `Continue from page ${issue.page + 1}` : 'Read'), href: appUrl(`/comics/read/${issue.id}`)},
            {label: issue.finished ? 'Mark as unread' : 'Mark as read', onClick: () => toggleRead(issue)},
            {label: 'Download', href: appUrl(`/comics/issue/${issue.id}/download`)},
        ];
    }

    let menuItems = readerItems;
    if (!window.isAdmin) return;

    // --- Admins ---
    const upload = document.getElementById('issueUpload');
    let uploadFor = null;

    menuItems = (issue, anchor) => {
        const out = issue.released;
        const findable = !issue.has_file && out && issue.status !== 'snatched';
        return [
            ...readerItems(issue),
            findable ? {label: 'Find now', onClick: () => findNow(issue)} : null,
            findable && window.pickRelease ? {label: 'Choose a release…', onClick: () => pickRelease({kind: 'comic', id: issue.id, label: `${issue.series} #${issue.number}`, onGrab: () => { issue.status = 'snatched'; showStatus(issue); }})} : null,
            !issue.has_file && issue.status !== 'snatched' ? {label: issue.status === 'wanted' ? 'Skip' : 'Want', onClick: () => setStatus(issue, issue.status === 'wanted' ? 'skipped' : 'wanted')} : null,
            {label: issue.has_file ? 'Replace the file…' : 'Add a file…', onClick: () => { uploadFor = issue; upload.click(); }},
            issue.has_file ? {label: 'Delete the file…', danger: true, onClick: () => confirmMenu(anchor, `Delete the file for #${issue.number}? This can’t be undone.`, [{label: 'Keep it'}, {label: 'Delete the file', danger: true, onClick: () => deleteFile(issue)}])} : null,
            issue.original_filename ? {note: `Was ${issue.original_filename}`} : null,
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
            showToast(`Downloading #${issue.number}`, 'success');
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

    // All / Have.
    const filter = document.querySelector('[aria-label="Show issues"]');
    if (filter) filter.addEventListener('click', (e) => {
        const button = e.target.closest('[data-filter]');
        if (!button) return;
        setRadio(filter, button);
        const show = button.dataset.filter;
        wall.querySelectorAll('[data-issue-id]').forEach(el => { el.hidden = show === 'have' && el.dataset.have !== '1'; });
    });

    // Select (from ⋯), then Want or Skip.
    const bulk = document.getElementById('bulk');
    function updateBulk() {
        if (!bulk) return;
        bulk.querySelector('#bulkCount').textContent = selected.size ? `${selected.size} chosen` : 'Choose issues';
        bulk.querySelectorAll('[data-bulk]').forEach(b => { b.disabled = !selected.size; });
    }
    function startSelect() {
        selecting = true;
        wall.classList.add('is-selecting');
        bulk.hidden = false;
        filter.hidden = true;
        updateBulk();
    }
    function endSelect() {
        selecting = false;
        selected.clear();
        wall.classList.remove('is-selecting');
        wall.querySelectorAll('.is-selected').forEach(el => el.classList.remove('is-selected'));
        bulk.hidden = true;
        filter.hidden = false;
    }
    if (bulk) {
        bulk.querySelector('#selectDone').addEventListener('click', endSelect);
        bulk.addEventListener('click', async (e) => {
            const button = e.target.closest('[data-bulk]');
            if (!button) return;
            try {
                await comicsApi('/issues/bulk', {method: 'POST', body: {ids: [...selected], status: button.dataset.bulk}});
                selected.forEach(id => { const issue = issues.get(String(id)); issue.status = button.dataset.bulk; showStatus(issue); });
                endSelect();
            } catch (err) { showToast(err.message, 'error'); }
        });
    }

    async function setMonitor(value) {
        try {
            const data = await comicsApi(`/series/${seriesId}`, {method: 'PATCH', body: {monitor: value}});
            head.dataset.monitor = data.monitor;
            // Every missing issue's status may have changed; read them again.
            const page = await fetch(location.href).then(r => r.text());
            const fresh = JSON.parse(new DOMParser().parseFromString(page, 'text/html').getElementById('issuesData').textContent);
            fresh.forEach(f => { const issue = issues.get(String(f.id)); if (issue) { Object.assign(issue, f); showStatus(issue); } });
            showToast(value === 'none' ? 'Getting no issues on its own' : `Getting ${value === 'all' ? 'all missing issues' : 'new issues'}${data.wanted ? ` · ${data.wanted} wanted` : ''}`, 'success');
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function refresh() {
        try {
            const data = await comicsApi(`/series/${seriesId}/refresh`, {method: 'POST'});
            if (data.added) window.location.reload();
            else showToast('Up to date');
        } catch (err) { showToast(err.message, 'error'); }
    }

    async function findWanted() {
        showToast('Looking for wanted issues…');
        try {
            const data = await comicsApi(`/series/${seriesId}/search`, {method: 'POST'});
            if (data.error) showToast(data.grabbed ? `Found ${data.grabbed}, but ${data.error}` : data.error, 'error');
            else if (data.grabbed) showToast(`Downloading ${data.grabbed} issue${data.grabbed === 1 ? '' : 's'}`, 'success');
            else showToast('Nothing new yet');
            if (data.grabbed) setTimeout(() => window.location.reload(), 1200);
        } catch (err) { showToast(err.message, 'error'); }
    }

    function stopFollowing(anchor) {
        const hasFiles = [...issues.values()].some(i => i.has_file);
        const leave = async (files) => {
            try {
                await comicsApi(`/series/${seriesId}${files ? '?files=1' : ''}`, {method: 'DELETE'});
                window.location = appUrl('/comics/');
            } catch (err) { showToast(err.message, 'error'); }
        };
        const name = head.querySelector('.meta-title').textContent;
        confirmMenu(anchor, `Stop following ${name}?`, hasFiles
            ? [{label: 'Keep the files', onClick: () => leave(false)}, {label: 'Delete the files too', danger: true, onClick: () => leave(true)}, {label: 'Cancel'}]
            : [{label: 'Cancel'}, {label: 'Stop following', danger: true, onClick: () => leave(false)}]);
    }

    document.addEventListener('click', (e) => {
        const button = e.target.closest('[data-action="series-menu"], [data-action="refresh"]');
        if (!button) return;
        if (button.dataset.action === 'refresh') return refresh();
        const local = head.dataset.provider === 'local';
        openMenu(button, [
            ...(local ? [] : MONITOR_LABELS.map(([value, label]) => ({label, checked: head.dataset.monitor === value, onClick: () => setMonitor(value)}))),
            wall ? {label: 'Choose issues…', onClick: startSelect} : null,
            local ? null : {label: 'Find wanted issues now', onClick: findWanted},
            local ? null : {label: 'Refresh details', onClick: refresh},
            head.dataset.source ? {label: `Open on ${head.dataset.provider === 'metron' ? 'Metron' : 'ComicVine'}`, href: head.dataset.source, external: true} : null,
            {label: 'Stop following…', danger: true, onClick: () => stopFollowing(button)},
        ]);
    });
}

const PAGES = {series: initSeries, 'series-detail': initSeriesDetail};
document.addEventListener('DOMContentLoaded', () => {
    const init = PAGES[document.body.dataset.page];
    if (init) init();
});
