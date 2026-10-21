// Toasts: non-blocking notices that slide in bottom-right and dismiss
// themselves. Shared by the books and comics pages (see _layout.html).
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
