import { getInvoice, getCompany, markInvoicePaid } from '../lib/api.js';
import { money, formatDate, statusClass } from '../lib/format.js';

export function invoiceDetailPage() {
  return {
    money, formatDate, statusClass,
    invoice: null,
    company: { company_name: '', logo_url: '', address: '' },
    async init() {
      const id = this.$root.route.split('/')[2];
      const userId = this.$root.session?.user?.id || 'local';
      this.invoice = await getInvoice(userId, id);
      this.company = await getCompany(userId);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    async markPaid() {
      const userId = this.$root.session?.user?.id || 'local';
      const updated = await markInvoicePaid(userId, this.invoice.id);
      this.invoice = { ...this.invoice, status: updated?.status || 'paid' };
    }
  };
}
