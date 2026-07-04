import { nav } from './components/Nav.js';
import { flavors } from './components/Flavors.js';
import { reservation } from './components/Reservation.js';
import { contactForm } from './components/ContactForm.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('nav', nav);
  Alpine.data('flavors', flavors);
  Alpine.data('reservation', reservation);
  Alpine.data('contactForm', contactForm);
});

document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined') lucide.createIcons();
});
