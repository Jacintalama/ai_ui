import { appShell } from './components/AppShell.js';
import { loginForm } from './components/LoginForm.js';
import { todoApp } from './components/TodoApp.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('appShell', appShell);
  Alpine.data('loginForm', loginForm);
  Alpine.data('todoApp', todoApp);
});

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) window.lucide.createIcons();
});
