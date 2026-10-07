import { portfolio } from './components/Portfolio.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('portfolio', portfolio);
});
