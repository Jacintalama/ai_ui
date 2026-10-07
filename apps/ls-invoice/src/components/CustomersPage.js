import { listCustomers, upsertCustomer, deleteCustomer } from '../lib/api.js';

export function customersPage() {
  return {
    customers: [],
    sortBy: 'name',
    modalOpen: false,
    form: { id: null, name: '', email: '', address: '' },
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      this.customers = await listCustomers(userId);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    get sortedCustomers() {
      const k = this.sortBy;
      return [...this.customers].sort((a, b) => String(a[k] || '').localeCompare(String(b[k] || '')));
    },
    openModal(c = null) {
      this.form = c
        ? { id: c.id, name: c.name, email: c.email || '', address: c.address || '' }
        : { id: null, name: '', email: '', address: '' };
      this.modalOpen = true;
    },
    async save() {
      const userId = this.$root.session?.user?.id || 'local';
      const saved = await upsertCustomer(userId, this.form);
      const idx = this.customers.findIndex(c => c.id === saved.id);
      if (idx >= 0) this.customers[idx] = saved;
      else this.customers.push(saved);
      this.modalOpen = false;
    },
    async remove(c) {
      if (!confirm(`Delete ${c.name}?`)) return;
      await deleteCustomer(c.id);
      this.customers = this.customers.filter(x => x.id !== c.id);
    }
  };
}
