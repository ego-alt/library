// Adding comic files (admins). The comics shelf's + takes one file and shows
// what it matched (by its ComicInfo or its name) to check before it's filed,
// or a series to choose, as a book gets its review panel. Downloads lists the
// files waiting in the import folder (from downloads, or dropped there) the
// same way, a row each.

(() => {
const COMIC_FILES = /\.(cbz|cbr|cb7|zip|rar|7z)$/i;

function describe(data) {
    return [data.imported.length || !(data.unmatched.length || data.failed.length) ? `Added ${data.imported.length}.` : null, data.unmatched.length ? `${data.unmatched.length} need${data.unmatched.length === 1 ? 's' : ''} a series.` : null, data.failed.length ? `${data.failed.length} couldn’t be opened.` : null].filter(Boolean).join(' ');
}

/** A file in the import folder as a row (Downloads › Needs a series): what
 * it looks like it is, then its series, number, Add and Delete.
 * `onChange(issue)` runs after it's filed (with the issue) or deleted. */
function fileRow(file, series, onChange) {
    const startOn = (file.series && file.series.id) || file.guess || '';
    const seriesSelect = h('select', {class: 'meta-input', 'aria-label': 'Series'},
        h('option', {value: ''}, 'Choose a series…'),
        series.map(([id, name]) => h('option', {value: id, selected: id === startOn}, name)),
        h('option', {value: 'new'}, 'A new series (from the file)…'));
    const number = h('input', {class: 'meta-input input--short', type: 'text', inputmode: 'decimal', value: (file.issue && file.issue.number) || file.parsed.number || '', 'aria-label': 'Issue number', placeholder: '#'});
    const newName = h('input', {class: 'meta-input', type: 'text', value: file.parsed.series || '', 'aria-label': 'Series name', hidden: true});
    const add = h('button', {type: 'button', class: 'btn btn-primary', disabled: !startOn, onclick: async (e) => {
        const body = {path: file.path, number: number.value};
        if (seriesSelect.value === 'new') body.new_series = newName.value;
        else body.series_id = Number(seriesSelect.value);
        e.currentTarget.textContent = 'Adding…';
        await busy(e.currentTarget, async () => {
            try {
                const issue = await apiFetch('/api/import/file', {method: 'POST', body});
                showToast(`Added ${issue.series} #${issue.number}`, 'success', {label: 'Open', onClick: () => { window.location = appUrl(`/comics/series/${issue.series_id}`); }});
                onChange(issue);
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
            onChange(null);
        } catch (err) { showToast(err.message, 'error'); }
    }}])}, 'Delete');
    const name = file.path;
    const guess = [file.parsed.series, file.parsed.number ? `#${file.parsed.number}` : null].filter(Boolean).join(' ');
    return h('li', {class: 'entry entry--import'},
        h('div', {class: 'entry__main'},
            h('span', {class: 'entry__title'}, file.issue ? file.issue.label : (guess ? `${guess}?` : name)),
            h('span', {class: 'entry__meta'}, [name, formatSize(file.size)].filter(Boolean).join(' · ')),
            h('span', {class: 'entry__hint'}, file.issue ? 'Matched by its name and details: check the series and number, then Add.' : file.reason),
            h('div', {class: 'entry__controls'}, seriesSelect, newName, number, add, remove)));
}

/** Fills `list` with the files waiting in the import folder; resolves with
 * how many there are. */
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

/** One comic from a shelf's +, checked before it's filed, in the same card
 * a book gets (the details panel: cover, title and its line, fields, then
 * Add to library). Closing it unadded asks first, then lets the file go. */
async function reviewOne(file) {
    const form = new FormData();
    form.append('file', file);
    const toast = showToast(`Reading ${file.name}…`, 'info', null, {sticky: true});
    let data;
    try {
        data = await apiFetch('/api/import/stage', {method: 'POST', form});
    } catch (e) {
        dismissToast(toast);
        return showToast(e.message, 'error');
    }
    dismissToast(toast);
    const staged = data.file;
    const stagePath = `/api/import/stage/${staged.path.split('/').map(encodeURIComponent).join('/')}`;
    const startOn = (staged.series && staged.series.id) || staged.guess || '';
    const seriesName = id => (data.series.find(([i]) => String(i) === String(id)) || [, ''])[1];

    const title = h('h2', {class: 'meta-title', id: 'reviewTitle'});
    const seriesSelect = h('select', {class: 'meta-input', 'aria-label': 'Series'},
        h('option', {value: ''}, 'Choose a series…'),
        data.series.map(([id, name]) => h('option', {value: id, selected: id === startOn}, name)),
        h('option', {value: 'new'}, 'A new series (from the file)…'));
    const newName = h('input', {class: 'meta-input', type: 'text', value: staged.parsed.series || '', placeholder: 'Series name'});
    const newField = h('label', {class: 'meta-field', hidden: true}, h('span', {class: 'meta-label'}, 'New series'), newName);
    const number = h('input', {class: 'meta-input', type: 'text', inputmode: 'decimal', value: (staged.issue && staged.issue.number) || staged.parsed.number || '', placeholder: '#'});
    const save = h('button', {type: 'button', class: 'save-button btn btn-primary'}, 'Add to library');
    const footer = h('footer', {class: 'meta-footer'},
        h('span', {class: 'meta-footer-info'}, staged.issue ? 'Matched by its name and details.' : staged.reason),
        h('div', {class: 'meta-footer-actions'}, save));
    const cover = h('figure', {class: 'meta-cover'},
        h('span', {class: 'cover-blank', 'aria-hidden': 'true'}, staged.parsed.series || staged.name),
        h('img', {src: appUrl(`${stagePath}/cover`), alt: '', onerror: (e) => e.currentTarget.remove()}));
    const overlay = h('div', {class: 'metadata-overlay', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'reviewTitle', style: 'display: flex'},
        h('div', {class: 'metadata-content'},
            h('button', {class: 'close-metadata btn btn-ghost', 'aria-label': 'Close', dataset: {close: ''}}, iconEl('x')),
            h('header', {class: 'meta-header'}, title, h('p', {class: 'meta-author'}, staged.name)),
            h('section', {class: 'meta-body'}, cover,
                h('div', {class: 'meta-fields'},
                    h('label', {class: 'meta-field'}, h('span', {class: 'meta-label'}, 'Series'), seriesSelect),
                    newField,
                    h('label', {class: 'meta-field'}, h('span', {class: 'meta-label'}, 'Issue'), number))),
            footer));

    function sync() {
        const isNew = seriesSelect.value === 'new';
        newField.hidden = !isNew;
        const name = isNew ? newName.value.trim() : seriesName(seriesSelect.value);
        title.textContent = name ? `${name}${number.value.trim() ? ` #${number.value.trim()}` : ''}` : 'Which series is it?';
        save.disabled = !seriesSelect.value;
    }
    [seriesSelect, newName, number].forEach(el => el.addEventListener('input', sync));
    seriesSelect.addEventListener('change', sync);
    sync();

    let filed = false;
    save.addEventListener('click', async () => {
        const body = {number: number.value};
        if (seriesSelect.value === 'new') body.new_series = newName.value;
        else body.series_id = Number(seriesSelect.value);
        save.textContent = 'Adding…';
        await busy(save, async () => {
            try {
                const issue = await apiFetch(stagePath, {method: 'POST', body});
                filed = true;
                close();
                showToast(`Added ${issue.series} #${issue.number}`, 'success', {label: 'Open', onClick: () => { window.location = appUrl(`/comics/series/${issue.series_id}`); }});
                setTimeout(() => window.location.reload(), 900);
            } catch (err) { showToast(err.message, 'error'); }
        });
        save.textContent = 'Add to library';
    });

    function close() {
        overlay.remove();
        document.removeEventListener('keydown', onKey);
        if (!filed) apiFetch(stagePath, {method: 'DELETE'}).catch(() => {});
    }
    // As the book card does: closing before adding asks first.
    function requestClose() {
        if (footer.querySelector('.discard-bar')) return;
        const keep = h('button', {type: 'button', class: 'btn btn-secondary', onclick: () => bar.remove()}, 'Keep editing');
        const bar = h('div', {class: 'discard-bar', role: 'alertdialog', 'aria-label': 'Not added yet'},
            h('span', {}, 'This comic hasn’t been added yet.'), keep,
            h('button', {type: 'button', class: 'btn btn-danger', onclick: close}, 'Discard comic'));
        footer.prepend(bar);
        keep.focus();
    }
    function onKey(e) {
        if (e.key !== 'Escape') return;
        const bar = footer.querySelector('.discard-bar');
        bar ? bar.remove() : requestClose();
    }
    overlay.addEventListener('click', (e) => { if (e.target === overlay || e.target.closest('[data-close]')) requestClose(); });
    document.addEventListener('keydown', onKey);
    document.body.append(overlay);
    (seriesSelect.value ? number : seriesSelect).focus();
}

/** The shelf's +: one file at a time, so each can be checked. */
function attachAdd(button, input) {
    const handle = (files) => {
        const list = [...files].filter(f => COMIC_FILES.test(f.name));
        if (!list.length) return showToast('That isn’t a comic file.', 'error');
        if (list.length > 1) return showToast('Add comics one at a time, so each can be checked.', 'error');
        reviewOne(list[0]);
    };
    button.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { handle(input.files); input.value = ''; });
    const zone = document.getElementById('dropZone');
    if (zone) enableDropZone(zone, handle);
}

window.comicImport = {attachAdd, fillWaiting, describe};
})();
