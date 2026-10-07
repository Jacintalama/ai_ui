import { navigation } from './components/Navigation.js';
import { programs } from './components/Programs.js';
import { trainers } from './components/Trainers.js';
import { contactForm } from './components/ContactForm.js';

document.addEventListener('alpine:init', () => {
    Alpine.data('navigation', navigation);
    Alpine.data('programs', programs);
    Alpine.data('trainers', trainers);
    Alpine.data('contactForm', contactForm);
});
