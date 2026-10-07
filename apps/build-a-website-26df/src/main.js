import { nav } from './components/Nav.js';
import { services } from './components/Services.js';
import { projects } from './components/Projects.js';
import { testimonials } from './components/Testimonials.js';
import { contact } from './components/Contact.js';

document.addEventListener('alpine:init', () => {
  window.Alpine.data('nav', nav);
  window.Alpine.data('services', services);
  window.Alpine.data('projects', projects);
  window.Alpine.data('testimonials', testimonials);
  window.Alpine.data('contact', contact);
});
