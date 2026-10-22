// Settings (folded at the foot of Downloads): one form saved as a whole, a Save bar that shows only
// when something has changed, and Test buttons that try a section with what's
// on the form (saved or not). Helpers are in ui.js.

const settingsApi = (path, options) => apiFetch(`/api/settings${path}`, options);

function initSettings() {
    const form = document.getElementById('settingsForm');
    const indexerList = document.getElementById('indexerList');
    const template = document.getElementById('indexerTemplate');
    const saveBar = document.getElementById('saveBar');
    let saved = null;  // what the server last sent, to discard back to

    // --- Indexers: one line each, opened to edit. ---
    function summarize(el) {
        const field = key => el.querySelector(`[data-key="${key}"]`);
        el.querySelector('.indexer__name').textContent = field('name').value || field('url').value || 'New indexer';
        let host = '';
        try { host = new URL(field('url').value).host; } catch (e) { /* not a URL yet */ }
        el.querySelector('.indexer__meta').textContent = [field('kind').value === 'torznab' ? 'Torznab' : 'Newznab', host, field('enabled').checked ? null : 'off'].filter(Boolean).join(' · ');
    }

    function addIndexer(indexer = {kind: 'newznab', enabled: true, categories: '7030', book_categories: '7020'}, open = false) {
        const el = template.content.firstElementChild.cloneNode(true);
        el.querySelectorAll('[data-key]').forEach(field => {
            const value = indexer[field.dataset.key];
            if (field.type === 'checkbox') field.checked = value !== false;
            else field.value = value ?? '';
        });
        el.querySelector('details').open = open;
        el.addEventListener('input', () => summarize(el));
        el.querySelector('[data-indexer-remove]').addEventListener('click', () => { el.remove(); changed(); });
        el.querySelector('[data-indexer-test]').addEventListener('click', (e) => test(e.currentTarget, 'indexer', indexerValues(el)));
        summarize(el);
        indexerList.append(el);
        return el;
    }

    function indexerValues(el) {
        const indexer = {};
        el.querySelectorAll('[data-key]').forEach(field => { indexer[field.dataset.key] = field.type === 'checkbox' ? field.checked : field.value.trim(); });
        return indexer;
    }

    // --- Download clients: folded, with a word on whether each is set up. ---
    function clientStates() {
        let anyClient = false;
        document.querySelectorAll('details.client').forEach(el => {
            const name = el.dataset.client;
            const address = name === 'blackhole' ? form.elements.blackhole_dir.value.trim() : form.elements[`${name}.url`].value.trim();
            el.querySelector('.client__state').textContent = address || 'Not set up';
            el.classList.toggle('is-set', Boolean(address));
            if (address && name !== 'blackhole') anyClient = true;
        });
        // Only a client in another container needs its folders mapped.
        document.getElementById('pathMap').hidden = !anyClient && !form.elements['path_map.remote_path'].value;
    }

    // --- Filling, collecting, saving ---
    function fill(values) {
        saved = values;
        form.querySelectorAll('[name]').forEach(field => {
            const [key, sub] = field.name.split('.');
            let value = sub ? (values[key] || {})[sub] : values[key];
            if (Array.isArray(value)) value = value.join(', ');
            if (field.type === 'checkbox') field.checked = Boolean(value);
            else field.value = value ?? '';
        });
        indexerList.replaceChildren();
        values.indexers.forEach(i => addIndexer(i));
        clientStates();
        saveBar.hidden = true;
    }

    function collect() {
        const values = {};
        form.querySelectorAll('[name]').forEach(field => {
            const [key, sub] = field.name.split('.');
            const value = field.type === 'checkbox' ? field.checked : (field.type === 'number' ? Number(field.value) : field.value.trim());
            if (sub) (values[key] = values[key] || {})[sub] = value;
            else values[key] = value;
        });
        values.indexers = [...indexerList.children].map(indexerValues);
        return values;
    }

    function changed() {
        saveBar.hidden = false;
        clientStates();
    }

    async function save() {
        const button = saveBar.querySelector('[type="submit"]');
        await busy(button, async () => {
            try {
                fill(await settingsApi('', {method: 'PUT', body: collect()}));
                showToast('Settings saved', 'success');
            } catch (e) { showToast(e.message, 'error'); }
        });
    }

    // What a Test button tries: its own section, as it is on the form.
    function sectionValues(what) {
        const all = collect();
        if (what === 'comicvine') return {comicvine_api_key: all.comicvine_api_key};
        if (what === 'metron') return {metron_username: all.metron_username, metron_password: all.metron_password};
        if (what === 'blackhole') return {blackhole_dir: all.blackhole_dir};
        return all[what];
    }

    async function test(button, what, values) {
        const label = button.textContent;
        button.textContent = 'Testing…';
        await busy(button, async () => {
            try {
                const data = await settingsApi('/test', {method: 'POST', body: {what, values}});
                showToast(data.message, 'success');
            } catch (e) { showToast(e.message, 'error'); }
        });
        button.textContent = label;
    }

    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
    form.addEventListener('click', (e) => {
        const button = e.target.closest('[data-test]');
        if (button) test(button, button.dataset.test, sectionValues(button.dataset.test));
    });
    document.getElementById('discardSettings').addEventListener('click', () => fill(saved));
    document.getElementById('addIndexer').addEventListener('click', () => {
        addIndexer(undefined, true).querySelector('[data-key="name"]').focus();
        changed();
    });
    window.addEventListener('beforeunload', (e) => { if (!saveBar.hidden) e.preventDefault(); });
    settingsApi('').then(fill).catch(e => showToast(e.message, 'error'));
}

document.addEventListener('DOMContentLoaded', initSettings);
