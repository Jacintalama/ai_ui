import { supabase, supabaseConnected } from '../lib/supabase.js';

export function appShell() {
  return {
    session: null,
    page: 'Overview',
    theme: 'dark',
    supabaseConnected,
    navLinks: [
      { label: 'Overview', icon: 'layout-dashboard' },
      { label: 'Reports', icon: 'line-chart' },
      { label: 'Users', icon: 'users' },
      { label: 'Settings', icon: 'settings' }
    ],
    init() {
      const stored = localStorage.getItem('dashboard-theme');
      if (stored) this.theme = stored;

      if (supabaseConnected) {
        supabase.auth.getSession().then(({ data }) => { this.session = data.session; });
        supabase.auth.onAuthStateChange((_e, s) => { this.session = s; });
      } else {
        this.session = { user: { id: 'local', email: 'demo@local.dev' } };
      }
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
      // Re-render icons whenever page changes
      this.$watch('page', () => this.$nextTick(() => window.lucide && window.lucide.createIcons()));
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('dashboard-theme', this.theme);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
      // Notify charts of theme change
      window.dispatchEvent(new Event('theme-change'));
    },
    async signOut() {
      if (supabaseConnected) await supabase.auth.signOut();
      else this.session = null;
    },
    drawSparkline(canvas, data) {
      if (!canvas || !data) return;
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      const max = Math.max(1, ...data);
      ctx.beginPath();
      data.forEach((v, i) => {
        const x = (i / (data.length - 1)) * w;
        const y = h - (v / max) * (h - 4) - 2;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = '#6366f1';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      // Subtle fill
      ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
      ctx.fillStyle = 'rgba(99,102,241,0.10)';
      ctx.fill();
    }
  };
}
