// Adding comic files (admins): the comics shelf's + and drop, and the files
// that need a series. A file that matches an issue (by its ComicInfo or its
// name) is filed straight away; one that doesn't waits in the import folder
// and is matched here: pick its series (the closest is chosen already), check
// the number, Add. Downloads lists the same waiting files.

(() => {
const COMIC_FILES = /\.(cbz|cbr|cb7|zip|rar|7z|epub)$/i;

function describe(data) {
    return [data.imported.length || !(data.unmatched.length || data.failed.length) ? `Added ${data.imported.length}.` : null, data.unmatched.length ? `${data.unmatched.length} need${data.unmatched.length === 1 ? 's' : ''} a series.` : null, data.failed.length ? `${data.failed.length} couldn’t be opened.` : null].filter(Boolean).join(' ');
}

/** Sends files to the import folder and imports them. Resolves with
 * {imported, unmatched, failed}, or null when nothing was sent. */
async function sendFiles(fileList) {
    const files = [...fileList].filter(f => COMIC_FILES.test(f.name));
    if (!files.length) {
        showToast('Those aren’t comics.', 'error');
        return null;
    }
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    const toast = showToast(`Adding ${files.length} file${files.length === 1 ? '' : 's'}…`, 'info', null, {sticky: true});
    try {
        const data = await apiFetch('/api/import/upload', {method: 'POST', form});
        dismissToast(toast);
        showToast(describe(data), data.failed.length ? 'error' : 'success');
        return data;
    } catch (e) {
        dismissToast(toast);
        showToast(e.message, 'error');
        return null;
    }
}

/** A waiting file as a row: what it looks like it is, then its series,
 * number, Add and Delete. `onChange` runs after it's filed or deleted. */
function fileRow(file, series, onChange) {
    const startOn = file.guess || (file.series && file.series.id) || '';
    const seriesSelect = h('select', {class: 'meta-input', 'aria-label': 'Series'},
        h('option', {value: ''}, 'Choose a series…'),
        series.map(([id, name]) => h('option', {value: id, selected: id === startOn}, name)),
        h('option', {value: 'new'}, 'A new series (from the file)…'));
    const number = h('input', {class: 'meta-input input--short', type: 'text', inputmode: 'decimal', value: file.parsed.number || '', 'aria-label': 'Issue number', placeholder: '#'});
    const newName = h('input', {class: 'meta-input', type: 'text', value: file.parsed.series || '', 'aria-label': 'Series name', hidden: true});
    const add = h('button', {type: 'button', class: 'btn btn-primary', disabled: !startOn, onclick: async (e) => {
        const body = {path: file.path, number: number.value};
        if (seriesSelect.value === 'new') body.new_series = newName.value;
        else body.series_id = Number(seriesSelect.value);
        e.currentTarget.textContent = 'Adding…';
        await busy(e.currentTarget, async () => {
            try {
                const issue = await apiFetch('/api/import/file', {method: 'POST', body});
                showToast(`Filed as ${issue.series} #${issue.number}`, 'success', {label: 'Open', onClick: () => { window.location = appUrl(`/comics/series/${issue.series_id}`); }});
                onChange();
            } catch (err) { showToast(err.message, 'error'); }
        });
    }}, 'Add');
    seriesSelect.addEventListener('change', () => {
        newName.hidden = seriesSelect.value !== 'new';
        add.disabled = !seriesSelect.value;
    });
    const remove = h('button', {type: 'button', class: 'btn btn-ghost danger-text', onclick: (e) => confirmMenu(e.currentTarget, `Delete ${file.path}? This can’t be undone.`, [{label: 'Keep it'}, {label: 'Delete the file', danger: true, onClick: async () => {
        try {
            await apiFetch(`/api/import/file?path=${encodeURIComponent(file.path)}`, {method: 'DELETE'});
            showToast(`Deleted ${file.path}`);
            onChange();
        } catch (err) { showToast(err.message, 'error'); }
    }}])}, 'Delete');
    const guess = [file.parsed.series, file.parsed.number ? `#${file.parsed.number}` : null].filter(Boolean).join(' ');
    return h('li', {class: 'entry entry--import'},
        h('div', {class: 'entry__main'},
            h('span', {class: 'entry__title'}, guess ? `${guess}?` : file.path),
            h('span', {class: 'entry__meta'}, [guess ? file.path : null, formatSize(file.size)].filter(Boolean).join(' · ')),
            h('span', {class: 'entry__hint'}, file.issue ? `Will be filed as ${file.issue.label}` : file.reason),
            h('div', {class: 'entry__controls'}, seriesSelect, newName, number, add, remove)));
}

/** Fills `list` with the waiting files; resolves with how many there are. */
async function fillWaiting(list, onChange) {
    try {
        const data = await apiFetch('/api/import');
        list.replaceChildren(...data.files.map(f => fileRow(f, data.series, onChange)));
        return data.files.length;
    } catch (e) {
        list.replaceChildren(h('li', {class: 'empty-line'}, e.message));
        return 1;
    }
}

/** The files that need a series, in the details panel's sheet (the comics
 * shelf, after +). Closing it, or matching the last one, reloads the shelf
 * so new series and issues show. */
async function matchSheet() {
    const list = h('ol', {class: 'entries'});
    const overlay = h('div', {class: 'metadata-overlay', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'matchTitle', style: 'display: flex'},
        h('div', {class: 'metadata-content releases-panel'},
            h('button', {class: 'close-metadata btn btn-ghost', 'aria-label': 'Close', dataset: {close: ''}}, '×'),
            h('h3', {id: 'matchTitle'}, 'Needs a series'),
            h('p', {class: 'comics-hint'}, 'These didn’t match an issue on their own. Choose each one’s series and check the number.'),
            list));
    let changed = false;
    const close = () => { overlay.remove(); if (changed) window.location.reload(); };
    overlay.addEventListener('click', (e) => { if (e.target === overlay || e.target.closest('[data-close]')) close(); });
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape' && overlay.isConnected) { document.removeEventListener('keydown', esc); close(); } });
    document.body.append(overlay);
    const refill = async () => {
        changed = true;
        if (!(await fillWaiting(list, refill))) close();
    };
    if (!(await fillWaiting(list, refill))) close();
}

/** The shelf's +: pick files, add them, then match any that need it. */
function attachAdd(button, input) {
    const handle = async (files) => {
        const data = await sendFiles(files);
        if (!data) return;
        if (data.unmatched.length) matchSheet();
        else if (data.imported.length) setTimeout(() => window.location.reload(), 900);
    };
    button.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { handle(input.files); input.value = ''; });
    const zone = document.getElementById('dropZone');
    if (zone) enableDropZone(zone, handle);
}

window.comicImport = {attachAdd, fillWaiting, describe};
})();
