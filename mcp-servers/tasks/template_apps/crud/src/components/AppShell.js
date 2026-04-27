import { supabase, supabaseConnected } from '../lib/supabase.js';

export function appShell() {
  return {
    route: '/',
    session: null,
    supabaseConnected,
    init() {
      this.applyRoute();
      window.addEventListener('hashchange', () => this.applyRoute());

      if (supabaseConnected) {
        supabase.auth.getSession().then(({ data }) => {
          this.session = data.session;
          this.redirectIfNeeded();
        });
        supabase.auth.onAuthStateChange((_event, session) => {
          this.session = session;
          this.redirectIfNeeded();
        });
      } else {
        // No Supabase → fake a "session" so the UI works.
        this.session = { user: { id: 'local', email: 'you@local.dev' } };
      }

      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    applyRoute() {
      const hash = window.location.hash.replace(/^#/, '') || '/';
      this.route = hash;
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    redirectIfNeeded() {
      if (!this.session && this.route !== '/login') {
        window.location.hash = '#/login';
      } else if (this.session && this.route === '/login') {
        window.location.hash = '#/';
      }
    },
    async signOut() {
      if (supabaseConnected) await supabase.auth.signOut();
      else this.session = null;
      window.location.hash = '#/login';
    }
  };
}
