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

// Helper to update the dark mode icon
function updateDarkModeIcon() {
    const icon = document.getElementById('dark-mode-icon');
    if (icon) {
        icon.className = document.documentElement.classList.contains('dark-mode') ? 'fas fa-circle' : 'fas fa-moon';
    }
} 