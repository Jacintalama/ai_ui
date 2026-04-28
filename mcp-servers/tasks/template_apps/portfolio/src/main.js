import { portfolio } from './components/Portfolio.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('portfolio', portfolio);
});

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) window.lucide.createIcons();
});
