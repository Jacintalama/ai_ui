import { supabase, supabaseConnected } from '../lib/supabase.js';

export function appShell() {
  return {
    route: '/',
    session: null,
    supabaseConnected,
    navLinks: [
      { route: '/', label: 'Dashboard', icon: 'layout-dashboard' },
      { route: '/customers', label: 'Customers', icon: 'users' },
      { route: '/invoices', label: 'Invoices', icon: 'file-text' },
      { route: '/settings', label: 'Settings', icon: 'settings' }
    ],
    init() {
      this.applyRoute();
      window.addEventListener('hashchange', () => this.applyRoute());

      if (supabaseConnected) {
        supabase.auth.getSession().then(({ data }) => {
          this.session = data.session;
          this.redirectIfNeeded();
        });
        supabase.auth.onAuthStateChange((_e, s) => { this.session = s; this.redirectIfNeeded(); });
      } else {
        this.session = { user: { id: 'local', email: 'demo@local.dev' } };
      }

      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    applyRoute() {
      this.route = window.location.hash.replace(/^#/, '') || '/';
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    redirectIfNeeded() {
      if (!this.session && this.route !== '/login') window.location.hash = '#/login';
      else if (this.session && this.route === '/login') window.location.hash = '#/';
    },
    async signOut() {
      if (supabaseConnected) await supabase.auth.signOut();
      else this.session = null;
      window.location.hash = '#/login';
    }
  };
}
