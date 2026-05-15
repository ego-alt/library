/** Prefix for API and navigation paths when mounted under a subpath (e.g. /library). */
window.APP_ROOT = window.APP_ROOT || "";

function appUrl(path) {
    const root = window.APP_ROOT || "";
    return root + (path.startsWith("/") ? path : `/${path}`);
}
