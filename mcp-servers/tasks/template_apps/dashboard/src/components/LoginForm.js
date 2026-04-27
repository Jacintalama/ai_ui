import { supabase, supabaseConnected } from '../lib/supabase.js';

export function loginForm() {
  return {
    mode: 'signin', email: '', password: '', loading: false, error: null,
    init() {},
    async submit() {
      this.error = null; this.loading = true;
      try {
        if (!supabaseConnected) { this.$root.session = { user: { id: 'local', email: this.email || 'demo@local.dev' } }; return; }
        if (this.mode === 'signup') {
          const { error } = await supabase.auth.signUp({ email: this.email, password: this.password });
          if (error) throw error;
          alert('Check your email to confirm, then sign in.');
          this.mode = 'signin';
        } else {
          const { error } = await supabase.auth.signInWithPassword({ email: this.email, password: this.password });
          if (error) throw error;
        }
      } catch (e) { this.error = e?.message || 'Something went wrong.'; }
      finally { this.loading = false; }
    }
  };
}
