// Small helpers every page shares (see _layout.html): toasts, a JSON fetch,
// building elements, busy buttons and friendly sizes, times and dates.

// Toasts: non-blocking notices that slide in bottom-right and dismiss themselves.
function showToast(message, type = 'info', action = null, {sticky = false} = {}) {
    const container = document.getElementById('toastContainer');
    if (!container) {
        // Fallback if toast container isn't on this page (e.g. reader.html)
        console.warn('showToast called without #toastContainer:', message);
        return;
    }
    const toast = document.createElement('div');
    toast.className = `notice notice--${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    const text = document.createElement('span');
    text.textContent = message;
    toast.appendChild(text);
    // Optional action, e.g. {label: 'Undo', onClick() {...}}. Toasts with an
    // action stay up longer so there's time to use it.
    if (action) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'notice__action';
        btn.textContent = action.label;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dismissToast(toast);
            action.onClick();
        });
        toast.appendChild(btn);
    }
    toast.addEventListener('click', () => dismissToast(toast));
    container.appendChild(toast);
    // Force a reflow so the entrance transition fires
    requestAnimationFrame(() => toast.classList.add('notice--shown'));
    if (!sticky) setTimeout(() => dismissToast(toast), action ? 10000 : type === 'error' ? 6000 : 4000);
    return toast;
}

function dismissToast(toast) {
    if (!toast.parentNode) return;
    toast.classList.remove('notice--shown');
    toast.addEventListener(
        'transitionend',
        () => { if (toast.parentNode) toast.remove(); },
        { once: true },
    );
}

/** fetch() for this app's JSON API: sends JSON (or a FormData), and throws
 * the server's {error} message on a non-OK reply. */
async function apiFetch(path, {method = 'GET', body, form} = {}) {
    const options = {method, headers: {Accept: 'application/json'}};
    if (form) {
        options.body = form;
    } else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    const response = await fetch(appUrl(path), options);
    let data = {};
    try { data = await response.json(); } catch (e) { /* empty answer */ }
    if (!response.ok) {
        const error = new Error(data.error || `Something went wrong (${response.status}).`);
        error.status = response.status;
        throw error;
    }
    return data;
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

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "19 Aug" this year, "19 Aug 2025" otherwise (the comic_date filter's twin). */
function formatDate(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return `${d} ${MONTHS[m - 1]}${y === new Date().getFullYear() ? '' : ` ${y}`}`;
}

/** Files dropped anywhere on the page go to onFiles, with `zone` (a
 * .drop-zone) shown while they're dragged over. */
function enableDropZone(zone, onFiles) {
    let depth = 0;
    const hasFiles = e => Array.from(e.dataTransfer?.types || []).includes('Files');
    document.addEventListener('dragenter', (e) => {
        if (!hasFiles(e)) return;
        depth += 1;
        zone.hidden = false;
    });
    document.addEventListener('dragleave', (e) => {
        if (!hasFiles(e)) return;
        depth = Math.max(0, depth - 1);
        if (!depth) zone.hidden = true;
    });
    document.addEventListener('dragover', (e) => {
        if (hasFiles(e)) e.preventDefault();
    });
    document.addEventListener('drop', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        depth = 0;
        zone.hidden = true;
        onFiles(e.dataTransfer.files);
    });
}

/** One cover on the wall: the twin of the cover_card macro in _covers.html,
 * for covers added after the page loads. `extras` float over the cover. */
function coverCard({href, label, title, meta = [], cover = null, attrs = {}, imgAttrs = {}, classes = '', extras = []}) {
    const line = meta.filter(Boolean).join(' · ');
    return h('div', {class: `col-6 col-sm-4 col-md-3 mb-3${classes ? ` ${classes}` : ''}`, ...attrs},
        h('div', {class: 'book'},
            h('a', {href, 'aria-label': label},
                cover ? h('img', {src: cover, alt: label, loading: 'lazy', ...imgAttrs}) : h('span', {class: 'cover-blank'}, title)),
            extras),
        h('div', {class: 'book-caption', 'aria-hidden': 'true'},
            h('span', {class: 'book-caption__title'}, title),
            line ? h('span', {class: 'book-caption__author'}, line) : null));
}
