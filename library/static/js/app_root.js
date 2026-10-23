/** Prefix for API and navigation paths when mounted under a subpath (e.g. /library). */
window.APP_ROOT = window.APP_ROOT || "";

function appUrl(path) {
    const root = window.APP_ROOT || "";
    return root + (path.startsWith("/") ? path : `/${path}`);
}

/** An icon from the app's one set (static/icons.svg, Lucide), as markup:
 * icon('x'). Its size follows the text (1.15em); its colour, currentColor. */
function icon(name, cls = '') {
    return `<svg class="icon${cls ? ` ${cls}` : ''}" aria-hidden="true"><use href="${appUrl('/static/icons.svg')}#${name}"></use></svg>`;
}

/** The same, as an element, for code that builds elements. */
function iconEl(name, cls = '') {
    const t = document.createElement('template');
    t.innerHTML = icon(name, cls);
    return t.content.firstElementChild;
}
