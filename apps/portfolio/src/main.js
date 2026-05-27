import { nav } from './components/Nav.js';
import { hero } from './components/Hero.js';
import { skills } from './components/Skills.js';
import { projects } from './components/Projects.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('nav', nav);
  Alpine.data('hero', hero);
  Alpine.data('skills', skills);
  Alpine.data('projects', projects);
});

document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined') lucide.createIcons();
});
