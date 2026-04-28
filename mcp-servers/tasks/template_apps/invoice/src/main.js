import { appShell } from './components/AppShell.js';
import { loginForm } from './components/LoginForm.js';
import { dashboardPage } from './components/DashboardPage.js';
import { customersPage } from './components/CustomersPage.js';
import { invoicesListPage } from './components/InvoicesListPage.js';
import { invoiceFormPage } from './components/InvoiceFormPage.js';
import { invoiceDetailPage } from './components/InvoiceDetailPage.js';
import { settingsPage } from './components/SettingsPage.js';

document.addEventListener('alpine:init', () => {
  Alpine.data('appShell', appShell);
  Alpine.data('loginForm', loginForm);
  Alpine.data('dashboardPage', dashboardPage);
  Alpine.data('customersPage', customersPage);
  Alpine.data('invoicesListPage', invoicesListPage);
  Alpine.data('invoiceFormPage', invoiceFormPage);
  Alpine.data('invoiceDetailPage', invoiceDetailPage);
  Alpine.data('settingsPage', settingsPage);
});

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) window.lucide.createIcons();
});
