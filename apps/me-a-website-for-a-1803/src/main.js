import { products } from './components/Products.js';
import { contactForm } from './components/ContactForm.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('products', products);
  window.Alpine.data('contactForm', contactForm);
});
