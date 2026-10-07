import { site } from './components/Site.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('site', site);
});

window.addEventListener('load', () => {
  if (window.lucide) window.lucide.createIcons();
});
