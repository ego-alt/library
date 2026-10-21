// Comics pages: one small module per page, picked by <body data-page>.

const comicsApi = (path, options) => apiFetch(`/comics/api${path}`, options);

const STATUS_LABEL = {wanted: 'Wanted', skipped: 'Skipped', snatched: 'Downloading', downloaded: 'Have'};

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

// --- Follow a series --------------------------------------------------------

function initAdd() {
    const form = document.getElementById('lookupForm');
    const input = document.getElementById('lookupQuery');
    const status = document.getElementById('lookupStatus');
    const list = document.getElementById('lookupResults');
    const monitor = document.getElementById('monitorChoice');

    async function lookup() {
        const q = input.value.trim();
        if (!q) return;
        status.textContent = 'Looking…';
        list.replaceChildren();
        history.replaceState(null, '', `?q=${encodeURIComponent(q)}`);
        try {
            const data = await comicsApi(`/lookup?q=${encodeURIComponent(q)}`);
            status.textContent = data.results.length ? `${data.results.length} found on ${data.provider === 'comicvine' ? 'ComicVine' : 'Metron'}.` : 'Nothing by that name.';
            list.append(...data.results.map(row => lookupRow(row)));
        } catch (e) {
            status.textContent = e.message;
        }
    }

    // Results are covers like the library's: tap one to follow it.
    function lookupRow(row) {
        const followed = Boolean(row.followed_id);
        const card = coverCard({
            href: followed ? appUrl(`/comics/series/${row.followed_id}`) : '#',
            label: followed ? `${row.name}, followed` : `Follow ${row.name}`,
            title: row.name,
            meta: [row.start_year, row.publisher, row.issue_count ? `${row.issue_count} issues` : null],
            cover: row.cover_url,
            imgAttrs: {referrerpolicy: 'no-referrer'},
            attrs: {title: row.description ? (row.description.length > 300 ? `${row.description.slice(0, 300)}…` : row.description) : null},
            extras: [h('span', {class: `cover-flag cover-flag--action${followed ? ' is-on' : ''}`}, followed ? 'Following' : 'Follow')],
        });
        if (!followed) card.querySelector('.book > a').addEventListener('click', (e) => { e.preventDefault(); follow(card, row); });
        return card;
    }

    async function follow(card, row) {
        const flag = card.querySelector('.cover-flag');
        if (card.classList.contains('is-busy')) return;
        card.classList.add('is-busy');
        flag.textContent = 'Adding…';
        try {
            const data = await comicsApi('/series', {method: 'POST', body: {provider: row.provider, provider_id: row.provider_id, monitor: monitor.value}});
            window.location = data.url;
        } catch (e) {
            showToast(e.message, 'error');
            card.classList.remove('is-busy');
            flag.textContent = 'Follow';
        }
    }

    form.addEventListener('submit', (e) => { e.preventDefault(); lookup(); });
    if (input.value.trim()) lookup();
}

// --- One series -------------------------------------------------------------

// Mark an issue read (its last page) or unread (back to the start).
async function setRead(issue, read) {
    return comicsApi(`/issues/${issue.id}/progress`, {method: 'PUT', body: read ? {page: Math.max(0, (issue.pages || 1) - 1), finished: true} : {page: 0, finished: false}});
}

// Readers see the issues as covers; the ✓ on each marks it read.
function initIssueWall() {
    const wall = document.getElementById('issueWall');
    if (!wall) return;
    wall.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action="toggle-read"]');
        if (!button) return;
        const card = button.closest('[data-issue-id]');
        const read = button.getAttribute('aria-pressed') !== 'true';
        try {
            await setRead({id: card.dataset.issueId, pages: Number(card.dataset.pages) || 0}, read);
        } catch (err) { return showToast(err.message, 'error'); }
        button.setAttribute('aria-pressed', String(read));
        button.title = read ? 'Mark as unread' : 'Mark as read';
        card.classList.toggle('is-read', read);
        const meta = card.querySelector('.book-caption__author');
        if (meta) meta.textContent = [meta.textContent.split(' · ')[0], read ? 'Read' : (card.dataset.pages ? `${card.dataset.pages} pages` : '')].filter(Boolean).join(' · ');
    });
}

function initSeriesDetail() {
    const admin = window.isAdmin;
    const head = document.querySelector('.series-head');
    const seriesId = head.dataset.seriesId;
    head.querySelectorAll('.more').forEach(menu => menu.addEventListener('click', (e) => { if (e.target.closest('button')) menu.open = false; }));
    if (!admin) {
        initIssueWall();
        return;
    }
    const tbody = document.querySelector('#issueTable tbody');
    let issues = JSON.parse(document.getElementById('issuesData').textContent);
    let filter = 'all';
    const selected = new Set();
    const upload = document.getElementById('issueUpload');
    let uploadFor = null;

    function statusCell(issue) {
        if (!issue.released && issue.status !== 'downloaded') {
            return h('span', {class: `status-chip status-upcoming`, title: issue.status === 'wanted' ? 'Wanted when it comes out' : ''}, issue.status === 'wanted' ? 'Upcoming · wanted' : 'Upcoming');
        }
        return h('span', {class: `status-chip status-${issue.status}`}, STATUS_LABEL[issue.status] || issue.status);
    }

    function actions(issue) {
        const items = [];
        if (issue.has_file) {
            const read = issue.finished ? 'Read again' : (issue.page ? `Continue p. ${issue.page + 1}` : 'Read');
            items.push(h('a', {class: 'link-button link-button--strong', href: appUrl(`/comics/read/${issue.id}`)}, read));
        } else if (issue.status === 'wanted' || issue.status === 'skipped') {
            if (issue.released) {
                items.push(h('button', {type: 'button', class: 'link-button', onclick: (e) => searchNow(e.currentTarget, issue)}, 'Search'));
                items.push(h('button', {type: 'button', class: 'link-button', onclick: () => showReleases(issue)}, 'Pick'));
            }
            items.push(h('button', {type: 'button', class: 'link-button', onclick: () => setStatus(issue, issue.status === 'wanted' ? 'skipped' : 'wanted')}, issue.status === 'wanted' ? 'Skip' : 'Want'));
        }
        const more = h('details', {class: 'more'},
            h('summary', {'aria-label': 'More'}, '⋯'),
            h('div', {class: 'more__menu'},
                h('button', {type: 'button', onclick: () => { uploadFor = issue; upload.click(); }}, issue.has_file ? 'Replace file…' : 'Add a file…'),
                issue.has_file ? h('button', {type: 'button', onclick: () => toggleRead(issue)}, issue.finished ? 'Mark as unread' : 'Mark as read') : null,
                issue.has_file ? h('a', {href: appUrl(`/comics/issue/${issue.id}/download`)}, 'Download') : null,
                issue.has_file ? h('button', {type: 'button', class: 'danger-text', onclick: () => deleteFile(issue)}, 'Delete file') : null,
                issue.original_filename ? h('span', {class: 'more__note'}, `Was ${issue.original_filename}`) : null));
        items.push(more);
        return items;
    }

    function row(issue) {
        const cover = issue.cover ? h('img', {src: issue.cover, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer'}) : h('span', {class: 'thumb-blank'});
        return h('tr', {dataset: {id: issue.id}, class: issue.has_file ? 'is-have' : ''},
            h('td', {class: 'col-check'}, issue.has_file ? null : h('input', {type: 'checkbox', 'aria-label': `Select #${issue.number}`, checked: selected.has(issue.id), onchange: (e) => { e.target.checked ? selected.add(issue.id) : selected.delete(issue.id); updateBulk(); }})),
            h('td', {class: 'col-num'}, issue.number),
            h('td', {class: 'col-title'}, h('span', {class: 'thumb'}, cover), h('span', {}, issue.title || h('span', {class: 'text-muted'}, `Issue #${issue.number}`), issue.pages ? h('small', {class: 'text-muted'}, ` · ${issue.pages} pages`) : null)),
            h('td', {class: 'col-date'}, formatDate(issue.date)),
            h('td', {class: 'col-status'}, statusCell(issue)),
            h('td', {class: 'col-actions'}, actions(issue)));
    }

    function render() {
        const shown = issues.filter(i => filter === 'all' || (filter === 'have' ? i.has_file : !i.has_file));
        tbody.replaceChildren(...shown.map(row));
        if (!shown.length) tbody.append(h('tr', {}, h('td', {colspan: 6, class: 'comics-hint'}, filter === 'have' ? 'None of these yet.' : 'Nothing here.')));
    }

    function replace(updated) {
        issues = issues.map(i => i.id === updated.id ? {...i, ...updated} : i);
        render();
    }

    function updateBulk() {
        const bar = document.getElementById('bulkBar');
        bar.hidden = selected.size === 0;
        document.getElementById('bulkCount').textContent = `${selected.size} selected`;
    }

    async function setStatus(issue, status) {
        try {
            replace(await comicsApi(`/issues/${issue.id}`, {method: 'PATCH', body: {status}}));
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function searchNow(button, issue) {
        button.textContent = 'Searching…';
        await busy(button, async () => {
            try {
                const data = await comicsApi(`/issues/${issue.id}/search`, {method: 'POST'});
                replace(data.issue);
                showToast(`Grabbed ${data.download.title}`, 'success');
            } catch (e) { showToast(e.message, 'error'); }
        });
    }

    async function deleteFile(issue) {
        if (!confirm(`Delete the file for #${issue.number}?`)) return;
        try { replace(await comicsApi(`/issues/${issue.id}/file`, {method: 'DELETE'})); } catch (e) { showToast(e.message, 'error'); }
    }

    async function toggleRead(issue) {
        try {
            const data = await setRead(issue, !issue.finished);
            replace({id: issue.id, page: data.page, finished: data.finished});
        } catch (e) { showToast(e.message, 'error'); }
    }

    // Manual search: every release, with why the rejected ones don't fit.
    const overlay = document.getElementById('releasesOverlay');
    const releaseList = document.getElementById('releaseList');
    const releasesStatus = document.getElementById('releasesStatus');
    overlay.addEventListener('click', (e) => { if (e.target === overlay || e.target.closest('[data-close]')) overlay.style.display = 'none'; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') overlay.style.display = 'none'; });

    async function showReleases(issue) {
        document.getElementById('releasesTitle').textContent = `Releases for #${issue.number}`;
        releasesStatus.textContent = 'Asking the indexers…';
        releaseList.replaceChildren();
        overlay.style.display = 'flex';
        try {
            const data = await comicsApi(`/issues/${issue.id}/releases`);
            const fits = data.releases.filter(r => r.score >= 0).length;
            releasesStatus.textContent = (data.releases.length ? `${fits} of ${data.releases.length} fit this issue.` : 'The indexers have nothing for it.') + (data.errors.length ? ` ${data.errors.join(' ')}` : '');
            releaseList.append(...data.releases.map((r, index) => h('li', {class: r.score >= 0 ? 'release' : 'release is-rejected'},
                h('div', {class: 'release__text'},
                    h('strong', {}, r.title),
                    h('span', {class: 'text-muted'}, [r.indexer, r.protocol === 'torrent' ? `${r.seeders ?? '?'} seeders` : 'usenet', formatSize(r.size), r.published, r.note].filter(Boolean).join(' · '))),
                h('button', {type: 'button', class: r.score >= 0 ? 'btn btn-primary' : 'btn btn-secondary', onclick: (e) => grab(e.currentTarget, issue, data.token, index)}, 'Grab'))));
        } catch (e) {
            releasesStatus.textContent = e.message;
        }
    }

    async function grab(button, issue, token, index) {
        button.textContent = 'Sending…';
        await busy(button, async () => {
            try {
                const data = await comicsApi(`/issues/${issue.id}/grab`, {method: 'POST', body: {token, index}});
                replace(data.issue);
                overlay.style.display = 'none';
                showToast(`Sent ${data.download.title} to ${data.download.client}`, 'success');
            } catch (e) { showToast(e.message, 'error'); }
        });
    }

    upload.addEventListener('change', async () => {
        const file = upload.files[0];
        if (!file || !uploadFor) return;
        const form = new FormData();
        form.append('file', file);
        showToast(`Importing ${file.name}…`);
        try {
            replace(await comicsApi(`/issues/${uploadFor.id}/upload`, {method: 'POST', form}));
            showToast('Imported', 'success');
        } catch (e) { showToast(e.message, 'error'); }
        upload.value = '';
    });

    document.querySelector('[aria-label="Show issues"]').addEventListener('click', (e) => {
        const button = e.target.closest('[data-filter]');
        if (!button) return;
        setRadio(e.currentTarget, button);
        filter = button.dataset.filter;
        render();
    });
    document.getElementById('checkAll').addEventListener('change', (e) => {
        selected.clear();
        if (e.target.checked) issues.filter(i => !i.has_file && i.status !== 'snatched').forEach(i => selected.add(i.id));
        updateBulk();
        render();
    });
    document.getElementById('bulkBar').addEventListener('click', async (e) => {
        const button = e.target.closest('[data-bulk]');
        if (!button) return;
        try {
            await comicsApi('/issues/bulk', {method: 'POST', body: {ids: [...selected], status: button.dataset.bulk}});
            issues = issues.map(i => selected.has(i.id) && !i.has_file && i.status !== 'snatched' ? {...i, status: button.dataset.bulk} : i);
            selected.clear();
            document.getElementById('checkAll').checked = false;
            updateBulk();
            render();
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
            const files = issues.some(i => i.has_file) && confirm('Delete its files too? Cancel keeps them on disk.');
            try {
                await comicsApi(`/series/${seriesId}${files ? '?files=1' : ''}`, {method: 'DELETE'});
                window.location = appUrl('/comics/');
            } catch (err) { showToast(err.message, 'error'); }
        }
    });
    render();
}

// --- Downloads: wanted, in progress, import, coming up, history -------------

function initDownloads() {
    initWanted();
    initDownloadLists();
    initImport();
}

// Wanted issues come grouped by series; each group searches or skips as one.
function initWanted() {
    const section = document.getElementById('wanted');
    const count = section.querySelector('h2 .count');

    function removeRows(rows) {
        rows.forEach(row => {
            const group = row.closest('.wanted-group');
            row.remove();
            if (group && !group.querySelector('[data-issue-id]')) group.remove();
        });
        if (count) count.textContent = section.querySelectorAll('[data-issue-id]').length;
    }

    section.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action]');
        if (!button) return;
        e.preventDefault();  // buttons in a group's summary shouldn't fold it
        const row = button.closest('[data-issue-id]');
        const group = button.closest('.wanted-group');
        const action = button.dataset.action;
        if (action === 'search-all') {
            await comicsApi('/jobs/search', {method: 'POST'});
            showToast('Searching; grabs show up at the top of this page.', 'success');
        } else if (action === 'search-series') {
            button.textContent = 'Searching…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/series/${group.dataset.seriesId}/search`, {method: 'POST'});
                    showToast(data.grabbed ? `Grabbed ${data.grabbed}` : 'Nothing on the indexers yet', data.grabbed ? 'success' : 'info');
                    if (data.grabbed) window.location.reload();
                } catch (err) { showToast(err.message, 'error'); }
            });
        } else if (action === 'skip-series') {
            const rows = [...group.querySelectorAll('[data-issue-id]')];
            try {
                await comicsApi('/issues/bulk', {method: 'POST', body: {ids: rows.map(r => Number(r.dataset.issueId)), status: 'skipped'}});
                removeRows(rows);
            } catch (err) { showToast(err.message, 'error'); }
        } else if (action === 'search-issue') {
            button.textContent = 'Searching…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/issues/${row.dataset.issueId}/search`, {method: 'POST'});
                    showToast(`Grabbed ${data.download.title}`, 'success');
                    removeRows([row]);
                } catch (err) { showToast(err.message, 'error'); }
            });
        } else if (action === 'skip-issue') {
            try {
                await comicsApi(`/issues/${row.dataset.issueId}`, {method: 'PATCH', body: {status: 'skipped'}});
                removeRows([row]);
            } catch (err) { showToast(err.message, 'error'); }
        }
    });
}

function initDownloadLists() {
    const activeSection = document.getElementById('activeSection');
    const activeList = document.getElementById('activeList');
    const historyList = document.getElementById('historyList');
    const historyTitle = document.querySelector('#historySection h2');
    function downloadRow(d, active) {
        const label = d.issue ? h('a', {href: appUrl(`/comics/series/${d.issue.series_id}`)}, d.issue.label) : h('span', {class: 'text-muted'}, 'Issue removed');
        const state = active
            ? (d.status === 'importing' ? 'Importing' : d.client === 'blackhole' ? 'Waiting for the file' : `${Math.round((d.progress || 0) * 100)}%`)
            : (d.status === 'done' ? 'Done' : 'Failed');
        const buttons = active
            ? [h('button', {type: 'button', class: 'link-button', onclick: () => act(`/downloads/${d.id}/cancel`, 'POST', 'Cancelled')}, 'Cancel')]
            : [d.status === 'failed' && d.issue ? h('button', {type: 'button', class: 'link-button', onclick: () => act(`/downloads/${d.id}/retry`, 'POST', 'Grabbed another')}, 'Try another') : null,
               h('button', {type: 'button', class: 'link-button', onclick: () => act(`/downloads/${d.id}`, 'DELETE', 'Removed')}, 'Remove')];
        return h('li', {class: `download is-${d.status}`},
            h('div', {class: 'download__text'},
                h('span', {}, label, ' ', h('span', {class: `status-chip status-dl-${d.status}`}, state)),
                h('small', {class: 'text-muted'}, [d.title, d.indexer, formatSize(d.size), timeAgo(d.updated_at || d.created_at)].filter(Boolean).join(' · ')),
                d.error ? h('small', {class: 'download__error'}, d.error) : null,
                active && d.client !== 'blackhole' ? h('span', {class: 'have-meter'}, h('span', {style: `width: ${Math.round((d.progress || 0) * 100)}%`})) : null),
            h('div', {class: 'download__actions'}, buttons));
    }

    async function act(path, method, done) {
        try {
            await comicsApi(path, {method});
            showToast(done, 'success');
        } catch (e) { showToast(e.message, 'error'); }
        refresh();
    }

    async function refresh() {
        let data;
        try { data = await comicsApi('/activity'); } catch (e) { return; }
        activeSection.hidden = !data.active.length;
        activeList.replaceChildren(...data.active.map(d => downloadRow(d, true)));
        historyList.replaceChildren(...(data.history.length ? data.history.map(d => downloadRow(d, false)) : [h('li', {class: 'comics-hint'}, 'Nothing yet.')]));
        const failed = data.history.filter(d => d.status === 'failed').length;
        historyTitle.replaceChildren('History', data.history.length ? ' ' : '', data.history.length ? h('span', {class: 'text-muted history__count'}, failed ? `${data.history.length} · ${failed} failed` : String(data.history.length)) : '');
    }

    // Every 5 s while something is downloading, every 30 s otherwise.
    async function poll() {
        if (!document.hidden) await refresh();
        setTimeout(poll, activeSection.hidden ? 30000 : 5000);
    }
    poll();
}

// --- Import -----------------------------------------------------------------

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
                    await comicsApi('/import/file', {method: 'POST', body});
                    showToast('Imported', 'success');
                    load();
                } catch (err) { showToast(err.message, 'error'); }
            });
        }}, 'Import');
        const remove = h('button', {type: 'button', class: 'btn btn-ghost danger-text', onclick: async () => {
            if (!confirm(`Delete ${file.path}?`)) return;
            await comicsApi(`/import/file?path=${encodeURIComponent(file.path)}`, {method: 'DELETE'});
            load();
        }}, 'Delete');
        return h('li', {class: 'import-row'},
            h('div', {class: 'import-row__file'}, h('strong', {}, file.path), h('small', {class: 'text-muted'}, [formatSize(file.size), file.issue ? `Matches ${file.issue.label}; it's filed at the next import` : file.reason].filter(Boolean).join(' · '))),
            h('div', {class: 'import-row__match'}, seriesSelect, newName, number, go, remove));
    }

    async function load() {
        try {
            const data = await comicsApi('/import');
            waiting.hidden = !data.files.length;
            list.replaceChildren(...data.files.map(importRow));
        } catch (e) {
            waiting.hidden = false;
            list.replaceChildren(h('li', {class: 'comics-hint'}, e.message));
        }
    }

    async function send(fileList) {
        const files = [...fileList].filter(f => /\.(cbz|cbr|cb7|zip|rar|7z)$/i.test(f.name));
        if (!files.length) return showToast('Those aren’t comic files.', 'error');
        const form = new FormData();
        files.forEach(f => form.append('files', f));
        showToast(`Importing ${files.length} file${files.length === 1 ? '' : 's'}…`);
        try {
            const data = await comicsApi('/import/upload', {method: 'POST', form});
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
                const data = await comicsApi('/import/scan', {method: 'POST'});
                showToast(`Imported ${data.imported.length}`, 'success');
            } catch (err) { showToast(err.message, 'error'); }
        });
        load();
    });
    load();
}

const PAGES = {series: initSeries, add: initAdd, 'series-detail': initSeriesDetail, downloads: initDownloads};
document.addEventListener('DOMContentLoaded', () => {
    const init = PAGES[document.body.dataset.page];
    if (init) init();
});
