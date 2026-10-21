// Comics pages: one small module per page, picked by <body data-page>.

const comicsApi = async (path, {method = 'GET', body, form} = {}) => {
    const options = {method, headers: {Accept: 'application/json'}};
    if (form) {
        options.body = form;
    } else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    const response = await fetch(appUrl(`/comics/api${path}`), options);
    let data = {};
    try { data = await response.json(); } catch (e) { /* empty answer */ }
    if (!response.ok) {
        const error = new Error(data.error || `Something went wrong (${response.status}).`);
        error.status = response.status;
        throw error;
    }
    return data;
};

function toast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `notice notice--${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.textContent = message;
    el.addEventListener('click', () => el.remove());
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add('notice--shown'));
    setTimeout(() => {
        el.classList.remove('notice--shown');
        setTimeout(() => el.remove(), 250);
    }, type === 'error' ? 7000 : 3500);
}

function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'dataset') Object.assign(el.dataset, value);
        else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
        else el.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
}

function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    const mb = bytes / 1024 / 1024;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

function timeAgo(iso) {
    if (!iso) return '';
    const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
    return `${Math.round(seconds / 86400)} d ago`;
}

function setRadio(group, button) {
    group.querySelectorAll('[role="radio"]').forEach(b => b.setAttribute('aria-checked', String(b === button)));
}

async function busy(button, work) {
    const label = button.textContent;
    button.disabled = true;
    try {
        return await work();
    } finally {
        button.disabled = false;
        button.textContent = label;
    }
}

const STATUS_LABEL = {wanted: 'Wanted', skipped: 'Skipped', snatched: 'Downloading', downloaded: 'Have'};

// --- Series grid ----------------------------------------------------------

function initSeries() {
    const grid = document.getElementById('seriesGrid');
    if (!grid) return;
    const filter = document.getElementById('seriesFilter');
    filter.addEventListener('input', () => {
        const q = filter.value.trim().toLowerCase();
        for (const card of grid.children) card.hidden = q && !card.dataset.name.includes(q);
    });
    const sorter = document.querySelector('[aria-label="Sort series"]');
    sorter.addEventListener('click', (e) => {
        const button = e.target.closest('[data-sort]');
        if (!button) return;
        setRadio(sorter, button);
        const key = button.dataset.sort;
        const cards = [...grid.children].sort((a, b) => key === 'added' ? b.dataset.added.localeCompare(a.dataset.added) : a.dataset.name.localeCompare(b.dataset.name));
        grid.append(...cards);
    });
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

    function lookupRow(row) {
        const action = row.followed_id
            ? h('a', {class: 'btn btn-secondary', href: appUrl(`/comics/series/${row.followed_id}`)}, 'Following')
            : h('button', {type: 'button', class: 'btn btn-primary', onclick: (e) => follow(e.currentTarget, row)}, 'Follow');
        return h('li', {class: 'lookup-row'},
            row.cover_url ? h('img', {src: row.cover_url, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer'}) : h('span', {class: 'lookup-row__nocover'}),
            h('div', {class: 'lookup-row__text'},
                h('strong', {}, row.name),
                h('span', {class: 'text-muted'}, [row.start_year, row.publisher, row.volume ? `Vol. ${row.volume}` : null, row.issue_count ? `${row.issue_count} issues` : null].filter(Boolean).join(' · ')),
                row.description ? h('p', {}, row.description.length > 220 ? row.description.slice(0, 220) + '…' : row.description) : null),
            action);
    }

    async function follow(button, row) {
        button.disabled = true;
        button.textContent = 'Adding…';
        try {
            const data = await comicsApi('/series', {method: 'POST', body: {provider: row.provider, provider_id: row.provider_id, monitor: monitor.value}});
            window.location = data.url;
        } catch (e) {
            toast(e.message, 'error');
            button.disabled = false;
            button.textContent = 'Follow';
        }
    }

    form.addEventListener('submit', (e) => { e.preventDefault(); lookup(); });
    if (input.value.trim()) lookup();
}

// --- One series -------------------------------------------------------------

function initSeriesDetail() {
    const admin = window.isAdmin;
    const head = document.querySelector('.series-head');
    const seriesId = head.dataset.seriesId;
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
            if (!admin) items.push(h('a', {class: 'link-button', href: appUrl(`/comics/issue/${issue.id}/download`), 'aria-label': `Download #${issue.number}`}, 'Download'));
        }
        if (!admin) return items;
        if (issue.has_file) {
            // Reading is above; the rest is in the menu.
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
                issue.has_file ? h('a', {href: appUrl(`/comics/issue/${issue.id}/download`)}, 'Download') : null,
                issue.has_file ? h('button', {type: 'button', class: 'danger-text', onclick: () => deleteFile(issue)}, 'Delete file') : null,
                issue.original_filename ? h('span', {class: 'more__note'}, `Was ${issue.original_filename}`) : null));
        items.push(more);
        return items;
    }

    function row(issue) {
        const cover = issue.cover ? h('img', {src: issue.cover, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer'}) : h('span', {class: 'thumb-blank'});
        return h('tr', {dataset: {id: issue.id}, class: admin && issue.has_file ? 'is-have' : ''},
            admin ? h('td', {class: 'col-check'}, issue.has_file ? null : h('input', {type: 'checkbox', 'aria-label': `Select #${issue.number}`, checked: selected.has(issue.id), onchange: (e) => { e.target.checked ? selected.add(issue.id) : selected.delete(issue.id); updateBulk(); }})) : null,
            h('td', {class: 'col-num'}, issue.number),
            h('td', {class: 'col-title'}, h('span', {class: 'thumb'}, cover), h('span', {}, issue.title || h('span', {class: 'text-muted'}, `Issue #${issue.number}`), issue.pages ? h('small', {class: 'text-muted'}, ` · ${issue.pages} pages`) : null)),
            h('td', {class: 'col-date'}, issue.date || ''),
            admin ? h('td', {class: 'col-status'}, statusCell(issue)) : null,
            h('td', {class: 'col-actions'}, actions(issue)));
    }

    function render() {
        const shown = issues.filter(i => filter === 'all' || (filter === 'have' ? i.has_file : !i.has_file));
        tbody.replaceChildren(...shown.map(row));
        if (!shown.length) tbody.append(h('tr', {}, h('td', {colspan: 6, class: 'comics-hint'}, admin ? (filter === 'have' ? 'None of these yet.' : 'Nothing here.') : 'Nothing to read here yet.')));
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
        } catch (e) { toast(e.message, 'error'); }
    }

    async function searchNow(button, issue) {
        button.textContent = 'Searching…';
        await busy(button, async () => {
            try {
                const data = await comicsApi(`/issues/${issue.id}/search`, {method: 'POST'});
                replace(data.issue);
                toast(`Grabbed ${data.download.title}`, 'success');
            } catch (e) { toast(e.message, 'error'); }
        });
    }

    async function deleteFile(issue) {
        if (!confirm(`Delete the file for #${issue.number}?`)) return;
        try { replace(await comicsApi(`/issues/${issue.id}/file`, {method: 'DELETE'})); } catch (e) { toast(e.message, 'error'); }
    }

    if (!admin) {
        render();
        return;
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
                toast(`Sent ${data.download.title} to ${data.download.client}`, 'success');
            } catch (e) { toast(e.message, 'error'); }
        });
    }

    upload.addEventListener('change', async () => {
        const file = upload.files[0];
        if (!file || !uploadFor) return;
        const form = new FormData();
        form.append('file', file);
        toast(`Importing ${file.name}…`);
        try {
            replace(await comicsApi(`/issues/${uploadFor.id}/upload`, {method: 'POST', form}));
            toast('Imported', 'success');
        } catch (e) { toast(e.message, 'error'); }
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
        } catch (err) { toast(err.message, 'error'); }
    });

    const monitor = document.getElementById('monitorSelect');
    if (monitor) monitor.addEventListener('change', async () => {
        try {
            await comicsApi(`/series/${seriesId}`, {method: 'PATCH', body: {monitor: monitor.value}});
            window.location.reload();
        } catch (e) { toast(e.message, 'error'); }
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
                    toast(data.added ? `${data.added} new issue${data.added === 1 ? '' : 's'}` : 'Up to date', 'success');
                    if (data.added) window.location.reload();
                } catch (err) { toast(err.message, 'error'); }
            });
        } else if (action === 'search-series') {
            button.textContent = 'Searching…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/series/${seriesId}/search`, {method: 'POST'});
                    toast(data.grabbed ? `Grabbed ${data.grabbed}` : 'Nothing new on the indexers', data.grabbed ? 'success' : 'info');
                    if (data.grabbed) window.location.reload();
                } catch (err) { toast(err.message, 'error'); }
            });
        } else if (action === 'delete-series') {
            if (!confirm('Stop following this series?')) return;
            const files = issues.some(i => i.has_file) && confirm('Delete its files too? Cancel keeps them on disk.');
            try {
                await comicsApi(`/series/${seriesId}${files ? '?files=1' : ''}`, {method: 'DELETE'});
                window.location = appUrl('/comics/');
            } catch (err) { toast(err.message, 'error'); }
        }
    });
    render();
}

// --- Downloads: wanted, in progress, import, coming up, history -------------

function initDownloads() {
    initWanted();
    initDownloadLists();
    initImport();
    const format = new Intl.DateTimeFormat(undefined, {weekday: 'short', day: 'numeric', month: 'short'});
    document.querySelectorAll('.upcoming__day').forEach(el => {
        const [y, m, d] = el.dataset.date.split('-').map(Number);
        el.textContent = format.format(new Date(y, m - 1, d));
    });
}

function initWanted() {
    const section = document.getElementById('wanted');
    section.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-action]');
        if (!button) return;
        const row = button.closest('[data-issue-id]');
        const action = button.dataset.action;
        if (action === 'show-all') {
            section.querySelectorAll('.is-extra').forEach(el => { el.hidden = false; });
            button.remove();
        } else if (action === 'search-all') {
            await comicsApi('/jobs/search', {method: 'POST'});
            toast('Searching; grabs show up at the top of this page.', 'success');
        } else if (action === 'search-issue') {
            button.textContent = 'Searching…';
            await busy(button, async () => {
                try {
                    const data = await comicsApi(`/issues/${row.dataset.issueId}/search`, {method: 'POST'});
                    toast(`Grabbed ${data.download.title}`, 'success');
                    row.remove();
                } catch (err) { toast(err.message, 'error'); }
            });
        } else if (action === 'skip-issue') {
            try {
                await comicsApi(`/issues/${row.dataset.issueId}`, {method: 'PATCH', body: {status: 'skipped'}});
                row.remove();
            } catch (err) { toast(err.message, 'error'); }
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
            toast(done, 'success');
        } catch (e) { toast(e.message, 'error'); }
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

    refresh();
    setInterval(() => { if (!document.hidden) refresh(); }, 5000);
}

// Background jobs, at the foot of Settings.
function initJobs() {
    const table = document.getElementById('jobTable');
    if (!table) return;

    async function refresh() {
        let data;
        try { data = await comicsApi('/activity'); } catch (e) { return; }
        const worker = data.worker || {};
        table.querySelectorAll('[data-job]').forEach(rowEl => {
            const job = worker[rowEl.dataset.job];
            const msg = rowEl.querySelector('.job-msg');
            const pending = (worker.pending || []).includes(rowEl.dataset.job);
            msg.textContent = pending ? 'Starting…' : (job ? `${job.message} (${timeAgo(job.at)})` : 'Not run yet');
            msg.classList.toggle('danger-text', Boolean(job && !job.ok));
        });
        document.getElementById('workerState').textContent = worker.alive ? '' : 'The worker hasn’t checked in for a while; it starts when the app gets its first visit after a restart.';
    }

    table.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-run]');
        if (!button) return;
        await comicsApi(`/jobs/${button.dataset.run}`, {method: 'POST'});
        refresh();
    });
    refresh();
    setInterval(() => { if (!document.hidden) refresh(); }, 5000);
}

// --- Import -----------------------------------------------------------------

function initImport() {
    const list = document.getElementById('importList');
    const waiting = document.getElementById('importWaiting');
    const input = document.getElementById('importInput');
    const drop = document.getElementById('importDrop');
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
            else return toast('Pick a series first.', 'error');
            e.currentTarget.textContent = 'Importing…';
            await busy(e.currentTarget, async () => {
                try {
                    await comicsApi('/import/file', {method: 'POST', body});
                    toast('Imported', 'success');
                    load();
                } catch (err) { toast(err.message, 'error'); }
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
        if (!files.length) return toast('Those aren’t comic files.', 'error');
        const form = new FormData();
        files.forEach(f => form.append('files', f));
        toast(`Importing ${files.length} file${files.length === 1 ? '' : 's'}…`);
        try {
            const data = await comicsApi('/import/upload', {method: 'POST', form});
            toast(`Imported ${data.imported.length}${data.unmatched.length ? `; ${data.unmatched.length} to match by hand` : ''}${data.failed.length ? `; ${data.failed.length} unreadable` : ''}`, data.failed.length ? 'error' : 'success');
        } catch (e) { toast(e.message, 'error'); }
        load();
    }

    document.getElementById('importPick').addEventListener('click', () => input.click());
    input.addEventListener('change', () => { send(input.files); input.value = ''; });
    ['dragenter', 'dragover'].forEach(type => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach(type => drop.addEventListener(type, () => drop.classList.remove('is-over')));
    drop.addEventListener('drop', (e) => { e.preventDefault(); send(e.dataTransfer.files); });
    document.getElementById('importScan').addEventListener('click', async (e) => {
        e.currentTarget.textContent = 'Matching…';
        await busy(e.currentTarget, async () => {
            try {
                const data = await comicsApi('/import/scan', {method: 'POST'});
                toast(`Imported ${data.imported.length}`, 'success');
            } catch (err) { toast(err.message, 'error'); }
        });
        load();
    });
    load();
}

// --- Settings ---------------------------------------------------------------

function initSettings() {
    const form = document.getElementById('settingsForm');
    const indexerList = document.getElementById('indexerList');
    const template = document.getElementById('indexerTemplate');

    function addIndexer(indexer = {kind: 'newznab', enabled: true, categories: '7030'}) {
        const el = template.content.firstElementChild.cloneNode(true);
        el.querySelectorAll('[data-key]').forEach(field => {
            const value = indexer[field.dataset.key];
            if (field.type === 'checkbox') field.checked = value !== false;
            else field.value = value ?? '';
        });
        el.querySelector('[data-indexer-remove]').addEventListener('click', () => el.remove());
        el.querySelector('[data-indexer-test]').addEventListener('click', (e) => test(e.currentTarget, 'indexer', [...indexerList.children].indexOf(el)));
        indexerList.append(el);
    }

    function fill(values) {
        form.querySelectorAll('[name]').forEach(field => {
            const [key, sub] = field.name.split('.');
            let value = sub ? (values[key] || {})[sub] : values[key];
            if (Array.isArray(value)) value = value.join(', ');
            if (field.type === 'checkbox') field.checked = Boolean(value);
            else field.value = value ?? '';
        });
        indexerList.replaceChildren();
        values.indexers.forEach(addIndexer);
    }

    function collect() {
        const values = {};
        form.querySelectorAll('[name]').forEach(field => {
            const [key, sub] = field.name.split('.');
            const value = field.type === 'checkbox' ? field.checked : (field.type === 'number' ? Number(field.value) : field.value.trim());
            if (sub) (values[key] = values[key] || {})[sub] = value;
            else values[key] = value;
        });
        values.indexers = [...indexerList.children].map(el => {
            const indexer = {};
            el.querySelectorAll('[data-key]').forEach(field => { indexer[field.dataset.key] = field.type === 'checkbox' ? field.checked : field.value.trim(); });
            return indexer;
        });
        return values;
    }

    async function save() {
        const status = document.getElementById('saveStatus');
        try {
            fill(await comicsApi('/settings', {method: 'PUT', body: collect()}));
            status.textContent = 'Saved.';
            return true;
        } catch (e) {
            status.textContent = e.message;
            return false;
        }
    }

    // Tests use the saved settings, so save first.
    async function test(button, what, index) {
        button.textContent = '…';
        await busy(button, async () => {
            if (!(await save())) return;
            try {
                const data = await comicsApi('/settings/test', {method: 'POST', body: {what, index}});
                toast(data.message, 'success');
            } catch (e) { toast(e.message, 'error'); }
        });
    }

    form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
    form.addEventListener('click', (e) => {
        const button = e.target.closest('[data-test]');
        if (button) test(button, button.dataset.test);
    });
    document.getElementById('addIndexer').addEventListener('click', () => addIndexer());
    comicsApi('/settings').then(fill).catch(e => toast(e.message, 'error'));
    initJobs();
}

const PAGES = {series: initSeries, add: initAdd, 'series-detail': initSeriesDetail, downloads: initDownloads, settings: initSettings};
document.addEventListener('DOMContentLoaded', () => {
    const init = PAGES[document.body.dataset.page];
    if (init) init();
});
