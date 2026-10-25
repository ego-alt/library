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
    let response;
    try {
        response = await fetch(appUrl(path), options);
    } catch (e) {
        throw Object.assign(new Error("Couldn't reach the library. Check your connection and try again."), {status: 0});
    }
    let data = {};
    try { data = await response.json(); } catch (e) { /* empty answer */ }
    if (!response.ok) {
        const error = new Error(data.error || failureMessage(response.status));
        error.status = response.status;
        throw error;
    }
    return data;
}

/** What a failed request means, when the answer didn't say (nginx, not the
 * library, answered: too big, timed out, or the library is down). */
function failureMessage(status) {
    if (status === 413) return 'That file is too big to upload.';
    if (status === 504) return 'The library took too long to answer. Try again.';
    if (status === 502 || status === 503) return "The library isn't answering right now. Try again in a minute.";
    return `Something went wrong (error ${status}). Try again.`;
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

/** "just now", "5 minutes ago", "2 hours ago" within a day; after that the
 * date, as everywhere else ("19 Aug"). */
function timeAgo(iso) {
    if (!iso) return '';
    const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (seconds < 60) return 'just now';
    const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'} ago`;
    if (seconds < 3600) return plural(Math.round(seconds / 60), 'minute');
    if (seconds < 86400) return plural(Math.round(seconds / 3600), 'hour');
    return formatDate(new Date(iso).toISOString());
}

/** Remembers a shelf's tab (All, Unread, Reading, Finished) so it opens on
 * it next time; the server reads the cookie. */
/** A shelf's search box: "/" jumps to it, Enter puts a phone's keyboard away
 * so the results show, Esc clears it (as an input event, so whatever listens
 * to the box hears it). */
function bindSearchBox(input) {
    if (!input) return;
    document.addEventListener('keydown', (e) => {
        if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
        if ([...document.querySelectorAll('.metadata-overlay, .login-overlay')].some(el => getComputedStyle(el).display !== 'none')) return;
        e.preventDefault();
        input.focus();
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            input.blur();
        } else if (e.key === 'Escape' && input.value) {
            e.stopPropagation();
            input.value = '';
            input.dispatchEvent(new Event('input'));
        }
    });
}

/** Asks before a card with unsaved changes closes: a bar in its footer with
 * Keep editing and a quiet red discard, which stand in for the footer's own
 * buttons while it's up. */
function askToDiscard(footer, {message, discard, onDiscard}) {
    if (footer.querySelector('.discard-bar')) return;   // already asking
    const keep = h('button', {type: 'button', class: 'btn btn-secondary', onclick: () => bar.remove()}, 'Keep editing');
    const bar = h('div', {class: 'discard-bar', role: 'alertdialog', 'aria-label': 'Unsaved changes'},
        h('span', {}, message), keep,
        h('button', {type: 'button', class: 'btn btn-ghost danger-text', onclick: () => { bar.remove(); onDiscard(); }}, discard));
    footer.prepend(bar);
    keep.focus();
}

function rememberShelfView(shelf, view) {
    document.cookie = `shelf_view_${shelf}=${view}; path=${window.APP_ROOT || ''}/; max-age=31536000; samesite=lax`;
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
                h('span', {class: 'cover-blank', 'aria-hidden': 'true'}, title),
                cover ? h('img', {src: cover, alt: label, loading: 'lazy', onload: (e) => e.currentTarget.parentNode.classList.add('is-loaded'), onerror: (e) => e.currentTarget.remove(), ...imgAttrs}) : null),
            extras),
        h('div', {class: 'book-caption', 'aria-hidden': 'true'},
            h('span', {class: 'book-caption__title'}, title),
            line ? h('span', {class: 'book-caption__author'}, line) : null));
}

/** A small menu floating by `anchor` (it can't live inside a cover, which
 * clips what overflows). Items: {label, onClick, danger, checked} |
 * {label, href} | {note} | {ask} (a question heading the menu) | {divider}. */
let floatingMenu = null;
let _safeBottom = null;
function safeBottom() {
    if (_safeBottom === null) {
        const probe = h('div', {style: 'position:fixed;bottom:0;padding-bottom:env(safe-area-inset-bottom, 0px);visibility:hidden'});
        document.body.append(probe);
        _safeBottom = parseFloat(getComputedStyle(probe).paddingBottom) || 0;
        probe.remove();
    }
    return _safeBottom;
}
function closeMenu() {
    if (floatingMenu) floatingMenu.remove();
    floatingMenu = null;
}
function openMenu(anchor, items) {
    closeMenu();
    const menu = h('div', {class: 'float-menu', role: 'menu'}, items.filter(Boolean).map(item => {
        if (item.ask) return h('p', {class: 'float-menu__ask'}, item.ask);
        if (item.divider) return h('hr', {class: 'float-menu__rule'});
        if (item.note) return h('span', {class: 'float-menu__note'}, item.note);
        if (item.href) return h('a', {href: item.href, role: 'menuitem', target: item.external ? '_blank' : null, rel: item.external ? 'noopener noreferrer' : null}, item.label);
        const checkable = item.checked !== undefined;
        return h('button', {type: 'button', role: checkable ? 'menuitemradio' : 'menuitem', 'aria-checked': checkable ? String(Boolean(item.checked)) : null, class: item.danger ? 'danger-text' : null, onclick: () => { closeMenu(); item.onClick(); }}, item.label);
    }));
    document.body.append(menu);
    const rect = anchor.getBoundingClientRect();
    const width = menu.offsetWidth;
    // Clear of the home bar on phones.
    const room = window.innerHeight - safeBottom() - 8;
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    const below = rect.bottom + 4 + menu.offsetHeight < room;
    menu.style.left = `${left}px`;
    menu.style.top = `${below ? rect.bottom + 4 : Math.max(8, rect.top - 4 - menu.offsetHeight)}px`;
    floatingMenu = menu;
    menu.querySelector('button, a')?.focus();
}

/** Asks before something that can't be undone, in the app's own menu rather
 * than a browser dialog. The first choice is the safe one and has focus.
 * choices: [{label, onClick?, danger?}]; one without onClick just closes. */
function confirmMenu(anchor, question, choices) {
    openMenu(anchor, [{ask: question}, ...choices.map(c => ({...c, onClick: c.onClick || (() => {})}))]);
}
document.addEventListener('click', (e) => { if (floatingMenu && !floatingMenu.contains(e.target) && !e.target.closest('[data-menu-anchor]')) closeMenu(); }, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
window.addEventListener('scroll', closeMenu, {passive: true});
