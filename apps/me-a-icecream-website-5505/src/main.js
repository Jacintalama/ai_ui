import { iceCreamApp } from './components/IceCreamApp.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('iceCreamApp', iceCreamApp);
});
