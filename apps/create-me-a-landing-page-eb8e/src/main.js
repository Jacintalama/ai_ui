import { reserveForm } from './components/ReserveForm.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('reserveForm', reserveForm);
});
