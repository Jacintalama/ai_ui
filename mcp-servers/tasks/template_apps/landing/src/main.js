import { landingPage } from './components/LandingPage.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('landingPage', landingPage);
});

// Re-render Lucide icons whenever Alpine renders new DOM
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) window.lucide.createIcons();
});

// Re-create icons after Alpine has rendered x-for templates
document.addEventListener('alpine:initialized', () => {
  setTimeout(() => window.lucide && window.lucide.createIcons(), 0);
});
