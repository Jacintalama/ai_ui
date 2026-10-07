import { navigation } from './components/Navigation.js';

// Register Alpine.js components
document.addEventListener('alpine:init', () => {
  Alpine.data('navigation', navigation);
});

// Initialize Lucide icons after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
});
