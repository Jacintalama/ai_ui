import { getCompany, saveCompany } from '../lib/api.js';

export function settingsPage() {
  return {
    form: { company_name: '', logo_url: '', address: '', tax_rate: 0 },
    saved: false,
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      this.form = await getCompany(userId);
    },
    async save() {
      const userId = this.$root.session?.user?.id || 'local';
      await saveCompany(userId, this.form);
      this.saved = true;
      setTimeout(() => { this.saved = false; }, 2500);
    }
  };
}
