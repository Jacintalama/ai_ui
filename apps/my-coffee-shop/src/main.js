import { navbar } from './components/Navbar.js';
import { menu } from './components/Menu.js';
import { specials } from './components/Specials.js';
import { contactForm } from './components/ContactForm.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('navbar', navbar);
  Alpine.data('menu', menu);
  Alpine.data('specials', specials);
  Alpine.data('contactForm', contactForm);
});

document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined') lucide.createIcons();
});
