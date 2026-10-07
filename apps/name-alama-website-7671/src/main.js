import { formBuilder } from './components/FormBuilder.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('formBuilder', formBuilder);
});
