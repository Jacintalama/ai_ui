import { appShell } from './components/AppShell.js';
import { loginForm } from './components/LoginForm.js';
import { overviewPage } from './components/OverviewPage.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('appShell', appShell);
  Alpine.data('loginForm', loginForm);
  Alpine.data('overviewPage', overviewPage);
});

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) window.lucide.createIcons();
});
