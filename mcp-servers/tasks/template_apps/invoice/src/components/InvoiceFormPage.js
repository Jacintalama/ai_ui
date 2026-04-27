import { listCustomers, createInvoice, getCompany } from '../lib/api.js';
import { money } from '../lib/format.js';

export function invoiceFormPage() {
  return {
    money,
    customers: [],
    taxRate: 0,
    form: {
      customer_id: '',
      issue_date: new Date().toISOString().slice(0, 10),
      due_date: new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10),
      notes: '',
      items: [{ description: '', quantity: 1, unit_price: 0 }]
    },
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      this.customers = await listCustomers(userId);
      const company = await getCompany(userId);
      this.taxRate = Number(company?.tax_rate || 0);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    addLine() { this.form.items.push({ description: '', quantity: 1, unit_price: 0 }); },
    get subtotal() { return this.form.items.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0); },
    get tax() { return +(this.subtotal * this.taxRate / 100).toFixed(2); },
    get total() { return +(this.subtotal + this.tax).toFixed(2); },
    async save() {
      if (!this.form.customer_id) { alert('Select a customer'); return; }
      if (this.form.items.length === 0 || this.form.items.every(l => !l.description)) { alert('Add at least one line item'); return; }
      const userId = this.$root.session?.user?.id || 'local';
      const inv = await createInvoice(userId, { ...this.form, status: 'draft', tax_rate: this.taxRate });
      window.location.hash = `#/invoices/${inv.id}`;
    }
  };
}
