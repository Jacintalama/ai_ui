import { navBar, skillsSection, projectsSection, contactForm } from './components/LandingPage.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('navBar', navBar);
  Alpine.data('skillsSection', skillsSection);
  Alpine.data('projectsSection', projectsSection);
  Alpine.data('contactForm', contactForm);
});

document.addEventListener('alpine:initialized', () => {
  setTimeout(() => window.lucide && window.lucide.createIcons(), 0);
});
