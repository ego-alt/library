// Initialize dark mode on page load (for any deferred cases)
document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('darkMode') === 'enabled') {
        document.documentElement.classList.add('dark-mode');
        updateDarkModeIcon();
    }
});

// Toggle dark mode and update localStorage
function toggleDarkMode() {
    // Toggle dark mode on the <html> element
    const docElem = document.documentElement;
    docElem.classList.toggle('dark-mode');
    const isDarkMode = docElem.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDarkMode ? 'enabled' : 'disabled');
    updateDarkModeIcon();
}

// The bar's button shows the mode a click switches to: the sun at night,
// the moon by day.
function updateDarkModeIcon() {
    const slot = document.getElementById('dark-mode-icon');
    if (!slot) return;
    const dark = document.documentElement.classList.contains('dark-mode');
    slot.innerHTML = icon(dark ? 'sun' : 'moon');
    const button = slot.closest('button');
    if (button) button.setAttribute('aria-label', dark ? 'Day mode' : 'Night mode');
}
