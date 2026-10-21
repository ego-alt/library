// Comics pages: one small module per page, picked by <body data-page>.

const comicsApi = (path, options) => apiFetch(`/comics/api${path}`, options);

// --- The wall of series: one search box and All / Unread / Reading / Finished,
// like the books (main.js), filtered here since every series is on the page. ---

const SERIES_EMPTY = {
    unread: ['Nothing unread', 'You’ve opened every series here.'],
    reading: ['Nothing on the go', 'Series you start reading will appear here.'],
    finished: ['Nothing finished yet', 'Series you’ve read every issue of will appear here.'],
};

function initSeries() {
    const grid = document.getElementById('library');
    if (!grid) return;
    const search = document.getElementById('librarySearch');
    const empty = document.getElementById('emptyState');
    const filter = document.querySelector('.status-filter[aria-label="Reading status"]');
    const cards = [...grid.children];
    let view = filter.querySelector('[aria-checked="true"]').dataset.view;

    function apply() {
        const q = search.value.trim().toLowerCase();
        // What you read last comes first under Reading; A–Z everywhere else.
        const order = view === 'reading' ? [...cards].sort((a, b) => b.dataset.last.localeCompare(a.dataset.last)) : cards;
        grid.append(...order);
        let shown = 0;
        for (const card of cards) {
            card.hidden = (view !== 'all' && card.dataset.state !== view) || (q && !card.dataset.name.includes(q));
            if (!card.hidden) shown += 1;
        }
        empty.hidden = shown > 0;
        if (!shown) {
            const [title, body] = q ? [`Nothing matches "${search.value.trim()}"`, 'Try a different word, or clear the search.'] : SERIES_EMPTY[view];
            empty.querySelector('h3').textContent = title;
            empty.querySelector('p').textContent = body;
        }
    }

    filter.addEventListener('click', (e) => {
        const button = e.target.closest('[data-view]');
        if (!button || button.dataset.view === view) return;
        view = button.dataset.view;
        setRadio(filter, button);
        apply();
    });
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
    apply();
}

// --- One series: its issues as covers. Readers mark them read; admins also
// see the missing ones, faded, with what each is waiting on, and act on them
// from a cover's ⋯ menu or several at once with Select. ---

const MISSING_FLAG = {wanted: 'Wanted', snatched: 'Downloading', skipped: 'Skipped'};

// Mark an issue read (its last page) or unread (back to the start).
async function setRead(issue, read) {
    return comicsApi(`/issues/${issue.id}/progress`, {method: 'PUT', body: read ? {page: Math.max(0, (issue.pages || 1) - 1), finished: true} : {page: 0, finished: false}});
}

function initSeriesDetail() {
    const head = document.querySelector('.series-head');
    const seriesId = head.dataset.seriesId;
    const wall = document.getElementById('issueWall');
    const issues = new Map(JSON.parse(document.getElementById('issuesData').textContent).map(i => [String(i.id), i]));
    head.querySelectorAll('.more').forEach(menu => menu.addEventListener('click', (e) => { if (e.target.closest('button')) menu.open = false; }));

    const card = id => wall.querySelector(`[data-issue-id="${id}"]`);
    let selecting = false;  // admins' Select mode
    const selected = new Set();

    function showRead(issue, read) {
        const el = card(issue.id);
        const button = el.querySelector('[data-action="toggle-read"]');
        button.setAttribute('aria-pressed', String(read));
        button.title = read ? 'Mark as unread' : 'Mark as read';
        el.classList.toggle('is-read', read);
        const meta = el.querySelector('.book-caption__author');
        if (meta) meta.textContent = [formatDate(issue.date), read ? 'Read' : (issue.pages ? `${issue.pages} pages` : '')].filter(Boolean).join(' · ');
    }

    async function toggleRead(issue) {
        const read = !issue.finished;
        try {
            const data = await setRead(issue, read);
            Object.assign(issue, {page: data.page, finished: data.finished});
            showRead(issue, data.finished);
        } catch (e) { showToast(e.message, 'error'); }
    }

    // A missing issue's flag follows its status.
    function showStatus(issue) {
        const el = card(issue.id);
        if (!el || issue.has_file) return;
        el.className = el.className.replace(/\bstatus-\S+/g, '').trim() + ` status-${issue.status}`;
        const flag = el.querySelector('.cover-flag');
        if (flag && issue.released) flag.textContent = MISSING_FLAG[issue.status] || issue.status;
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
        const button = e.target.closest('[data-action]');
        if (button?.dataset.action === 'toggle-read') {
            toggleRead(issue);
        } else if (button?.dataset.action === 'menu') {
            openMenu(button, menuItems(issue));
        } else if (!issue.has_file && e.target.closest('.book > a')) {
            e.preventDefault();
            if (window.isAdmin) openMenu(e.target.closest('.book > a'), menuItems(issue));
        }
    });

    if (!window.isAdmin) return;

    // --- Admins ---
    const upload = document.getElementById('issueUpload');
    let uploadFor = null;

    function menuItems(issue) {
        const out = issue.released;
        return [
            issue.has_file ? {label: issue.finished ? 'Read again' : (issue.page ? `Continue p. ${issue.page + 1}` : 'Read'), href: appUrl(`/comics/read/${issue.id}`)} : null,
            issue.has_file ? {label: issue.finished ? 'Mark as unread' : 'Mark as read', onClick: () => toggleRead(issue)} : null,
            !issue.has_file && out && issue.status !== 'snatched' ? {label: 'Search now', onClick: () => searchNow(issue)} : null,
            !issue.has_file && out && issue.status !== 'snatched' && window.pickRelease ? {label: 'Pick a release…', onClick: () => pickRelease({kind: 'comic', id: issue.id, label: `#${issue.number}`, onGrab: () => { issue.status = 'snatched'; showStatus(issue); }})} : null,
            !issue.has_file && issue.status !== 'snatched' ? {label: issue.status === 'wanted' ? 'Skip' : 'Want', onClick: () => setStatus(issue, issue.status === 'wanted' ? 'skipped' : 'wanted')} : null,
            {label: issue.has_file ? 'Replace the file…' : 'Add a file…', onClick: () => { uploadFor = issue; upload.click(); }},
            issue.has_file ? {label: 'Download', href: appUrl(`/comics/issue/${issue.id}/download`)} : null,
            issue.has_file ? {label: 'Delete the file', danger: true, onClick: () => deleteFile(issue)} : null,
            issue.original_filename ? {note: `Was ${issue.original_filename}`} : null,
        ];
    }

    async function setStatus(issue, status) {
        try {
            Object.assign(issue, await comicsApi(`/issues/${issue.id}`, {method: 'PATCH', body: {status}}));
            showStatus(issue);
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function searchNow(issue) {
        showToast(`Searching for #${issue.number}…`);
        try {
            const data = await apiFetch(`/api/wanted/comic/${issue.id}/search`, {method: 'POST'});
            issue.status = data.status;
            showStatus(issue);
            showToast(`Grabbed ${data.download.title}`, 'success');
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function deleteFile(issue) {
        if (!confirm(`Delete the file for #${issue.number}?`)) return;
        try {
            await comicsApi(`/issues/${issue.id}/file`, {method: 'DELETE'});
            window.location.reload();
        } catch (e) { showToast(e.message, 'error'); }
    }

    upload.addEventListener('change', async () => {
        const file = upload.files[0];
        if (!file || !uploadFor) return;
        const form = new FormData();
        form.append('file', file);
        showToast(`Importing ${file.name}…`);
        try {
            await comicsApi(`/issues/${uploadFor.id}/upload`, {method: 'POST', form});
            window.location.reload();
        } catch (e) { showToast(e.message, 'error'); }
        upload.value = '';
    });

    // All / Have / Missing.
    document.querySelector('[aria-label="Show issues"]').addEventListener('click', (e) => {
        const button = e.target.closest('[data-filter]');
        if (!button) return;
        setRadio(e.currentTarget, button);
        const show = button.dataset.filter;
        wall.querySelectorAll('[data-issue-id]').forEach(el => { el.hidden = show !== 'all' && (el.dataset.have === '1') !== (show === 'have'); });
    });

    // Select, then Want or Skip.
    const toggle = document.getElementById('selectToggle');
    const bulk = toggle.parentElement;
    function updateBulk() {
        const count = bulk.querySelector('#bulkCount');
        count.textContent = `${selected.size} selected`;
        bulk.querySelectorAll('[data-bulk], #bulkCount').forEach(el => { el.hidden = !selecting || !selected.size; });
    }
    function endSelect() {
        selecting = false;
        selected.clear();
        wall.classList.remove('is-selecting');
        wall.querySelectorAll('.is-selected').forEach(el => el.classList.remove('is-selected'));
        toggle.textContent = 'Select';
        updateBulk();
    }
    toggle.addEventListener('click', () => {
        if (selecting) return endSelect();
        selecting = true;
        wall.classList.add('is-selecting');
        toggle.textContent = 'Done';
        updateBulk();
    });
    bulk.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-bulk]');
        if (!button) return;
        try {
            await comicsApi('/issues/bulk', {method: 'POST', body: {ids: [...selected], status: button.dataset.bulk}});
            selected.forEach(id => { const issue = issues.get(String(id)); issue.status = button.dataset.bulk; showStatus(issue); });
            endSelect();
        } catch (err) { showToast(err.message, 'error'); }
    });

    const monitor = document.getElementById('monitorSelect');
    if (monitor) monitor.addEventListener('change', async () => {
        try {
            await comicsApi(`/series/${seriesId}`, {method: 'PATCH', body: {monitor: monitor.value}});
            window.location.reload();
        } catch (e) { showToast(e.message, 'error'); }
    });
    head.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'refresh') {
            button.textContent = 'Refreshing…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/series/${seriesId}/refresh`, {method: 'POST'});
                    showToast(data.added ? `${data.added} new issue${data.added === 1 ? '' : 's'}` : 'Up to date', 'success');
                    if (data.added) window.location.reload();
                } catch (err) { showToast(err.message, 'error'); }
            });
        } else if (action === 'search-series') {
            button.textContent = 'Searching…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/series/${seriesId}/search`, {method: 'POST'});
                    showToast(data.grabbed ? `Grabbed ${data.grabbed}` : 'Nothing new on the indexers', data.grabbed ? 'success' : 'info');
                    if (data.grabbed) window.location.reload();
                } catch (err) { showToast(err.message, 'error'); }
            });
        } else if (action === 'delete-series') {
            if (!confirm('Stop following this series?')) return;
            const files = [...issues.values()].some(i => i.has_file) && confirm('Delete its files too? Cancel keeps them on disk.');
            try {
                await comicsApi(`/series/${seriesId}${files ? '?files=1' : ''}`, {method: 'DELETE'});
                window.location = appUrl('/comics/');
            } catch (err) { showToast(err.message, 'error'); }
        }
    });
}

const PAGES = {series: initSeries, 'series-detail': initSeriesDetail};
document.addEventListener('DOMContentLoaded', () => {
    const init = PAGES[document.body.dataset.page];
    if (init) init();
});
