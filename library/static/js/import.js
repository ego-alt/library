// Adding a comic (admins): the comics shelf's + takes one file and shows what
// it matched (by its ComicInfo or its name) to check before it's filed, or a
// series to choose, as a book gets its review panel.

(() => {
const COMIC_FILES = /\.(cbz|cbr|cb7|zip|rar|7z)$/i;

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
    const number = h('input', {class: 'meta-input', type: 'text', inputmode: 'decimal', enterkeyhint: 'done', value: (staged.issue && staged.issue.number) || staged.parsed.number || '', placeholder: '#'});
    const save = h('button', {type: 'button', class: 'save-button btn btn-ghost'}, 'Add to library');
    const footer = h('footer', {class: 'meta-footer is-dirty'},   // a comic not yet added is always something to save
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
    // Enter in the number (or a new series' name) adds it, as Save does on a book.
    [number, newName].forEach(el => el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !save.disabled) { e.preventDefault(); save.click(); }
    }));
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
                showToast(`Added ${issue.series} #${issue.number}`, 'info', {label: 'Open', onClick: () => { window.location = appUrl(`/comics/series/${issue.series_id}`); }});
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
        askToDiscard(footer, {message: 'This comic hasn’t been added yet.', discard: 'Discard comic', onDiscard: close});
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

window.comicImport = {attachAdd};
})();
