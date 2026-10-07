document.addEventListener('alpine:init', () => {
    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});

// Smooth scroll handling
document.addEventListener('DOMContentLoaded', () => {
    // Re-initialize icons after DOM is ready
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});
