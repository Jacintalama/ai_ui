import { listInvoices } from '../lib/api.js';
import { money, formatDate, statusClass } from '../lib/format.js';

export function invoicesListPage() {
  return {
    money, formatDate, statusClass,
    invoices: [],
    statusFilter: '',
    from: '',
    to: '',
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      this.invoices = await listInvoices(userId);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    get filtered() {
      return this.invoices.filter(i => {
        if (this.statusFilter && i.status !== this.statusFilter) return false;
        if (this.from && i.issue_date < this.from) return false;
        if (this.to && i.issue_date > this.to) return false;
        return true;
      });
    }
  };
}
