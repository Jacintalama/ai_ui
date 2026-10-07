import { listInvoices, listCustomers } from '../lib/api.js';
import { money, formatDate, statusClass } from '../lib/format.js';

export function dashboardPage() {
  return {
    money, formatDate, statusClass,
    invoices: [],
    customers: [],
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      this.invoices = await listInvoices(userId);
      this.customers = await listCustomers(userId);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    get totalInvoiced() { return this.invoices.reduce((s, i) => s + Number(i.total || 0), 0); },
    get totalPaid() { return this.invoices.filter(i => i.status === 'paid').reduce((s, i) => s + Number(i.total || 0), 0); },
    get outstanding() { return this.invoices.filter(i => i.status !== 'paid').reduce((s, i) => s + Number(i.total || 0), 0); },
    get kpis() {
      return [
        { label: 'Total invoiced', value: money(this.totalInvoiced), trend: 12 },
        { label: 'Paid', value: money(this.totalPaid), trend: 8 },
        { label: 'Outstanding', value: money(this.outstanding), trend: -3 },
        { label: 'Customers', value: this.customers.length, trend: 5 }
      ];
    },
    get recentInvoices() { return this.invoices.slice(0, 5); }
  };
}
